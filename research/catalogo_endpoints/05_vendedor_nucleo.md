# 05 · APIs de vendedor (núcleo): producto, global product, pedidos, envíos, logística, finanzas, promociones, devoluciones, optimización y traducción de imágenes

Catálogo preparado para **Corte (creator-hub)**. Fecha de la investigación: 15/11/2026. Solo se usó documentación; no se llamó a la API real.

## Resumen de la familia

1. Encontré **169 endpoints** de vendedor en esta familia: producto (72), pedidos (8), cumplimiento y envíos (30, incluye 1 de `supply_chain`), logística (7), finanzas (8), promociones (19), devoluciones y reembolsos (18), optimización bajo `/seller/202611` (3) y 4 de apoyo para tiendas (obtener `shop_cipher`). Todos están en la especificación OpenAPI que se genera de partner.tiktokshop.com/docv2 (versión `2026.11.13`).
2. **Todos piden un token de VENDEDOR** (`user_type` 0, 4 o 5) y casi todos piden `shop_cipher`. El token de creador de Corte (`user_type=1`) no sirve: TikTok indica que un token de creador y uno de vendedor «must not be reused interchangeably» (error `101000`). Hoy se pueden usar **0 de 169** con la cuenta de Corte.
3. Además, todos los scopes de esta familia siguen en **«Awaiting review»** para la app. Aunque una tienda autorizara la app, todavía no se podrían llamar.
4. Solo devuelven datos de **la tienda que autorizó la app** (`shop_cipher`, «authorization context»). Ningún endpoint da datos de productos de otras tiendas. La única excepción teórica es la búsqueda para auditorías de cumplimiento, y está pensada para proveedores de cumplimiento.
5. **No existe ningún endpoint de reseñas de producto en el Partner API.** La única API oficial de reseñas de TikTok Shop es la Research API (`POST https://open.tiktokapis.com/v2/research/tts/review/`). Es solo para investigadores sin fines comerciales y cubre productos que se venden en la UE, así que no aplica a Corte.
6. Su único valor real llegaría si **una tienda socia autorizara la app como vendedor**, por ejemplo la que hoy concentra la mayor parte de la comisión. Con esa autorización, ⭐ *Get Product* daría la descripción completa, los atributos, todas las imágenes, el video, los SKU con sus variantes e imágenes, la guía de tallas y el inventario. *Search Products*, *Inventory Search*, *Search Size Charts* y los cupones exclusivos para creador lo completarían.
7. Pedidos, finanzas, devoluciones, logística y envíos son la operación interna de la tienda. Traen datos personales de compradores y ningún campo de creador, video o `content_id`, así que su valor para Corte es bajo o nulo. La traducción de imágenes solo funciona para vendedores en la UE (valor nulo). Las sugerencias SEO no cubren México.
8. **Recomendación:** no pedir los scopes de pedidos, finanzas, envíos, devoluciones, global product, borrado ni escritura. Si se busca la ruta de «tienda socia», basta con `Product Basic` (clave probable `seller.product.basic`). Pedir scopes de más alarga la revisión y baja la tasa de autorización (docs locales `authorization-overview-202407.txt`).

### Abreviaturas usadas en todo el archivo

- **V+SC**: token de vendedor más `shop_cipher` (query). Es el caso normal.
- **V**: token de vendedor sin `shop_cipher` (`requiresShopCipher=false` en la spec). Son operaciones a nivel de vendedor o de vendedor global.
- **RV (requisito de vendedor)**: (1) TikTok aprueba el scope, que hoy está en «Awaiting review»; (2) una **tienda** autoriza la app con el enlace de vendedor `https://services.tiktokshop.com/open/authorize?service_id={service_id}`, lo que produce un token `user_type=0`; (3) la app obtiene el `cipher` con *Get Authorized Shops*; (4) la respuesta solo trae datos de **esa** tienda.
- **Valor** indica qué tan útil es para Corte: alto / medio / bajo / ninguno. «(cond.)» significa que el valor depende de que una tienda socia autorice la app.
- **Fuentes**:
  - **S**: spec OpenAPI `isaackogan/TikTok-Shop-Api-SDKs`, archivo `.openapi/tiktok-shop.openapi.yaml` (`info.version: 2026.11.13`, «Generated from the TikTok Shop Partner Center documentation (https://partner.tiktokshop.com/docv2)»). La leí desde `https://raw.githubusercontent.com/isaackogan/TikTok-Shop-Api-SDKs/main/.openapi/tiktok-shop.openapi.yaml` y crucé la lista de operaciones con `python/src/tiktok_shop_api/generated/_meta.py` (campo `requiresShopCipher`).
  - **R**: la misma spec mostrada por operación en `https://ttspa.docs.isaackogan.com/openapi/reference/operations/<operationid>/`. De ahí saqué los parámetros y campos a detalle.
  - **D**: la página oficial de cada endpoint (`x-tts-docs-url`): `https://partner.tiktokshop.com/docv2/page/<slug>`. Estas páginas se renderizan con JS y WebFetch no pudo leerlas (devolvieron solo el encabezado). Las cito como referencia oficial.
  - **L**: docs locales en `research/tiktok-docs/`.

---

## Tabla breve de TODOS los endpoints (169)

Columnas: nombre · método + path · scope según la spec (`x-tts-scopes`) · ¿sirve al creador? · valor. Las claves de scope de la app (`seller.*`) están en la sección «Mapeo de scopes».

### Producto (72)

| # | Nombre | Método + path | Scope (spec) | ¿Sirve al creador? | Valor |
|---|---|---|---|---|---|
| 1 | Get Brands | GET /product/202309/brands | Product Basic | No · RV | bajo |
| 2 | Create Custom Brands | POST /product/202309/brands | Product Basic | No · RV | ninguno |
| 3 | Get Categories | GET /product/202309/categories | Product Basic | No · RV | bajo |
| 4 | Recommend Category | POST /product/202309/categories/recommend | Product Basic | No · RV | ninguno |
| 5 | Get Category Attributes | GET /product/202309/categories/{category_id}/attributes | Product Basic | No · RV | bajo |
| 6 | Get Global Attributes | GET /product/202309/categories/{category_id}/global_attributes | Global Category Infomation | No · RV (global) | ninguno |
| 7 | Get Global Category Rules | GET /product/202309/categories/{category_id}/global_rules | Global Category Infomation | No · RV (global) | ninguno |
| 8 | Get Category Rules | GET /product/202309/categories/{category_id}/rules | Product Basic | No · RV | bajo |
| 9 | Upload Product File | POST /product/202309/files/upload | Product Basic | No · RV | ninguno |
| 10 | Get Global Categories | GET /product/202309/global_categories | Global Category Infomation | No · RV (global) | ninguno |
| 11 | Recommend Global Categories | POST /product/202309/global_categories/recommend | Global Category Infomation | No · RV (global) | ninguno |
| 12 | Create Global Product | POST /product/202309/global_products | Global Product Modify | No · RV (global) | ninguno |
| 13 | Delete Global Products | DELETE /product/202309/global_products | Global Product Delete | No · RV (global) | ninguno |
| 14 | Get Global Product | GET /product/202309/global_products/{global_product_id} | Global Product Information | No · RV (global) | bajo |
| 15 | Edit Global Product | PUT /product/202309/global_products/{global_product_id} | Global Product Modify | No · RV (global) | ninguno |
| 16 | Update Global Inventory | POST /product/202309/global_products/{global_product_id}/inventory/update | Global Product Modify | No · RV (global) | ninguno |
| 17 | Publish Global Product | POST /product/202309/global_products/{global_product_id}/publish | Global Product Modify | No · RV (global) | ninguno |
| 18 | Upload Product Image | POST /product/202309/images/upload | Product Basic | No · RV | ninguno |
| 19 | Inventory Search | POST /product/202309/inventory/search | Product Basic | No · RV | medio (cond.) |
| 20 | Create Product | POST /product/202309/products | Product Modify | No · RV | ninguno |
| 21 | Delete Products | DELETE /product/202309/products | Product Delete & Recover | No · RV | ninguno |
| 22 | Activate Products | POST /product/202309/products/activate | Product Basic | No · RV | ninguno |
| 23 | Deactivate Products | POST /product/202309/products/deactivate | Product Basic | No · RV | ninguno |
| 24 | Check Product Listing | POST /product/202309/products/listing_check | Product Basic; Product Optimization | No · RV | ninguno |
| 25 | Recover Products | POST /product/202309/products/recover | Product Delete & Recover | No · RV | ninguno |
| 26 | ⭐ Get Product | GET /product/202309/products/{product_id} | Product Basic | No · RV | **alto (cond.)** |
| 27 | Update Inventory | POST /product/202309/products/{product_id}/inventory/update | Product Modify | No · RV | ninguno |
| 28 | Update Price | POST /product/202309/products/{product_id}/prices/update | Product Modify | No · RV | ninguno |
| 29 | Search Global Products | POST /product/202312/global_products/search | Global Product Information | No · RV (global) | bajo |
| 30 | Check Listing Prerequisites | GET /product/202312/prerequisites | Product Basic | No · RV | ninguno |
| 31 | Optimize Images | POST /product/202404/images/optimize | Product Basic | No · RV | bajo |
| 32 | Get Product Diagnoses | GET /product/202405/products/diagnoses | Product Optimization | No · RV | bajo |
| 33 | Get Products SEO Words | GET /product/202405/products/seo_words | Product Basic | No · RV (sin MX) | ninguno |
| 34 | Get Recommended Product Title and Description | GET /product/202405/products/suggestions | Product Optimization | No · RV | bajo |
| 35 | Create Category Upgrade Task | POST /product/202407/products/category_upgrade_task | Product Basic | No · RV | ninguno |
| 36 | Search Size Charts | POST /product/202407/sizecharts/search | Product Basic | No · RV | medio (cond.) |
| 37 | Create Manufacturer | POST /product/202409/compliance/manufacturers | Product Basic | No · RV (solo UE) | ninguno |
| 38 | Partial Edit Manufacturer | POST /product/202409/compliance/manufacturers/{manufacturer_id}/partial_edit | Product Basic | No · RV (solo UE) | ninguno |
| 39 | Create Responsible Person | POST /product/202409/compliance/responsible_persons | Product Basic | No · RV (solo UE) | ninguno |
| 40 | Partial Edit Responsible Person | POST /product/202409/compliance/responsible_persons/{responsible_person_id}/partial_edit | Product Basic | No · RV (solo UE) | ninguno |
| 41 | Diagnose and Optimize Product | POST /product/202411/products/diagnose_optimize | Product Optimization | No · RV | bajo |
| 42 | Search Manufacturers | POST /product/202501/compliance/manufacturers/search | Product Basic | No · RV (solo UE) | ninguno |
| 43 | Search Responsible Persons | POST /product/202501/compliance/responsible_persons/search | Product Basic | No · RV (solo UE) | ninguno |
| 44 | Search Products | POST /product/202502/products/search | Product Basic | No · RV | medio (cond.) |
| 45 | Create Image Translation Tasks | POST /product/202505/images/translation_tasks | Product Optimization | No · RV (solo UE) | ninguno |
| 46 | Get Image Translation Tasks | GET /product/202506/images/translation_tasks | Product Optimization | No · RV (solo UE) | ninguno |
| 47 | Get Global Listing Rules | GET /product/202507/global_listing_rules | Product Basic | No · RV (global) | ninguno |
| 48 | Replicate Product | POST /product/202507/products/{product_id}/global_replicate | Product Modify | No · RV (global) | ninguno |
| 49 | Get Global Replicated Products | GET /product/202507/products/{product_id}/replicated_products | Product Basic | No · RV (global) | ninguno |
| 50 | Partial Edit Global Product | PUT /product/202509/global_products/{global_product_id}/partial_edit | Product Basic (según la spec) | No · RV (global) | ninguno |
| 51 | Edit Product | PUT /product/202509/products/{product_id} | Product Modify | No · RV | ninguno |
| 52 | Partial Edit Product | POST /product/202509/products/{product_id}/partial_edit | Product Modify | No · RV | ninguno |
| 53 | Search Products for Compliance Auditing | POST /product/202601/compliance/auditing/research | Product Basic | No (proveedor de cumplimiento) | bajo / no verificado |
| 54 | Get Product Package Recommendations | POST /product/202602/packages/recommend | Product Basic | No · RV | ninguno |
| 55 | Submit Size Chart Appeal | POST /product/202604/appeals/submit | Product Basic | No · RV | ninguno |
| 56 | List Opportunities | POST /product/202604/opportunities/query | Product Basic | No · RV | bajo |
| 57 | Get Submission Records | GET /product/202604/opportunities/submissions | Product Basic | No · RV | bajo |
| 58 | Get Opportunity Detail | GET /product/202604/opportunities/{opportunity_id} | Product Basic | No · RV | bajo |
| 59 | Submit Product via Opportunity | POST /product/202604/opportunities/{opportunity_id}/submit | Product Basic | No · RV | ninguno |
| 60 | Create GPA Upgrade Task | POST /product/202604/products/gpa_upgrade_task | Product Basic | No · RV (solo UE) | ninguno |
| 61 | List Product SKPP Statuses | POST /product/202606/skpps/search | Product Basic | No · RV | bajo |
| 62 | Get Shop SKPP Summary | GET /product/202606/skpps/sum | Product Basic | No · RV | ninguno |
| 63 | Get Product SKPP Detail | GET /product/202606/skpps/{product_id} | Product Basic | No · RV (solo US) | ninguno |
| 64 | Update Stock Operation Settings | POST /product/202608/inventory/operation/settings | Product Basic | No · RV | ninguno |
| 65 | Suggest Brands | POST /product/202609/brands/suggest | Product Basic | No · RV | ninguno |
| 66 | Predict Product Package Dimensions and Weight | POST /product/202609/products/package/predict | Product Basic | No · RV | ninguno |
| 67 | Recommend Required Product Properties | POST /product/202609/products/properties/recommend | Product Basic | No · RV | ninguno |
| 68 | Submit Strikethrough Price | POST /product/202609/products/{product_id}/strikethrough_price/submit | Product Basic | No · RV | ninguno |
| 69 | Create Image-Based Product Listing Task | POST /product/202610/image_listing_tasks | Product Basic | No · RV | ninguno |
| 70 | Get Product Property Recommendation Task | GET /product/202610/property_recommendation_tasks/{task_id} | Product Basic | No · RV | ninguno |
| 71 | Create Size Chart V2 | POST /product/202610/size_charts | Product Basic | No · RV | ninguno |
| 72 | Edit Size Chart V2 | POST /product/202610/size_charts/edit | Product Basic | No · RV | ninguno |

### Pedidos (8)

| # | Nombre | Método + path | Scope (spec) | ¿Sirve al creador? | Valor |
|---|---|---|---|---|---|
| 73 | Get Order List | POST /order/202309/orders/search | FS Order&Fulfillment Management; Order Information | No · RV | bajo |
| 74 | Search Orders by External Order Reference | POST /order/202406/orders/external_order_search | Read External Order References | No · RV | ninguno |
| 75 | Add External Order References | POST /order/202406/orders/external_orders | Write External Order References | No · RV | ninguno |
| 76 | Get External Order References | GET /order/202406/orders/{order_id}/external_orders | Read External Order References | No · RV | ninguno |
| 77 | Get Order Price Details | GET /order/202407/orders/{order_id}/price_detail | Order Information | No · RV | bajo |
| 78 | Get Order Detail | GET /order/202507/orders | FS Order&Fulfillment Management; Order Information | No · RV | bajo |
| 79 | Update the Blind Box Opening Results | POST /order/202605/orders/blind_box_result/callback | Order Information | No · RV | ninguno |
| 80 | Search POD Customization Details | POST /order/202606/pod_details/search | Order Information | No · RV | ninguno |

### Cumplimiento y envíos (30)

| # | Nombre | Método + path | Scope (spec) | ¿Sirve al creador? | Valor |
|---|---|---|---|---|---|
| 81 | Search Combinable Packages | GET /fulfillment/202309/combinable_packages/search | Package Split And Combine | No · RV | ninguno |
| 82 | Upload Proof of Delivery File | POST /fulfillment/202309/files/upload | Fulfillment Basic | No · RV | ninguno |
| 83 | Upload Proof of Delivery Image | POST /fulfillment/202309/images/upload | Fulfillment Basic | No · RV | ninguno |
| 84 | Get Order Split Attributes | GET /fulfillment/202309/orders/split_attributes | FS Order&Fulfillment Management, Package Split And Combine | No · RV | ninguno |
| 85 | Update Order Shipping Info | POST /fulfillment/202309/orders/{order_id}/shipping_info/update | Logistics Basic | No · RV | ninguno |
| 86 | Get Eligible Shipping Services | POST /fulfillment/202309/orders/{order_id}/shipping_services/query | Fulfillment Basic | No · RV (US/JP) | ninguno |
| 87 | Confirm Order Split | POST /fulfillment/202309/orders/{order_id}/split | FS Order&Fulfillment Management, Package Split And Combine | No · RV | ninguno |
| 88 | Get Order Tracking | GET /fulfillment/202309/orders/{order_id}/tracking | Logistics Basic | No · RV | bajo |
| 89 | Combine Package | POST /fulfillment/202309/packages/combine | Package Split And Combine | No · RV | ninguno |
| 90 | Update Package Delivery Status | POST /fulfillment/202309/packages/deliver | Update Delivery Status | No · RV (solo SEA) | ninguno |
| 91 | Search Package | POST /fulfillment/202309/packages/search | Fulfillment Basic | No · RV | bajo |
| 92 | Batch Ship Packages | POST /fulfillment/202309/packages/ship | FS Order&Fulfillment Management, Fulfillment Basic | No · RV | ninguno |
| 93 | Get Package Detail | GET /fulfillment/202309/packages/{package_id} | FS Order&Fulfillment Management, Fulfillment Basic | No · RV | bajo |
| 94 | Get Package Handover Time Slots | GET /fulfillment/202309/packages/{package_id}/handover_time_slots | Package Split And Combine | No · RV | ninguno |
| 95 | Ship Package | POST /fulfillment/202309/packages/{package_id}/ship | FS Order&Fulfillment Management, Fulfillment Basic | No · RV | ninguno |
| 96 | Get Package Shipping Document | GET /fulfillment/202309/packages/{package_id}/shipping_documents | FS Order&Fulfillment Management, Fulfillment Basic | No · RV | ninguno |
| 97 | Uncombine Packages | POST /fulfillment/202309/packages/{package_id}/uncombine | Package Split And Combine | No · RV | ninguno |
| 98 | Create First Mile Bundle | POST /fulfillment/202407/bundles | Fulfillment Basic | No · RV | ninguno |
| 99 | Upload Invoice | POST /fulfillment/202502/invoice/upload | Fulfillment Basic | No · RV (solo BR) | ninguno |
| 100 | Check TikTok Shipping and Collection by TikTok Coverage | GET /fulfillment/202508/tts_tracking_validation | Logistics Basic | No · RV (solo US) | ninguno |
| 101 | Create First Mile Bundle V2 | POST /fulfillment/202510/first_mile_bundle | Fulfillment Basic | No · RV | ninguno |
| 102 | Create Packages | POST /fulfillment/202512/packages | FS Order&Fulfillment Management; Fulfillment Basic | No · RV (US/UK/EMEA/JP) | ninguno |
| 103 | Submit Redemption Information | POST /fulfillment/202601/redeem_info/callback | Manage Seller Redeem Info Callback | No · RV | ninguno |
| 104 | Get POD Customization Details | POST /fulfillment/202606/pod_details/get | Manage Seller Redeem Info Callback | No · RV | ninguno |
| 105 | Get Order Customs Requirements | POST /fulfillment/202607/orders/customs_info/query | Fulfillment Basic | No · RV | ninguno |
| 106 | Submit Customs Clearance Information | POST /fulfillment/202607/orders/customs_info/submit | Fulfillment Basic | No · RV | ninguno |
| 107 | Tracking Status Update | POST /fulfillment/202609/order/sof/track/update | Fulfillment Basic | No · RV (US/BR) | ninguno |
| 108 | Mark Package As Shipped | POST /fulfillment/202610/orders/{order_id}/packages | FS Order&Fulfillment Management; Fulfillment Basic | No · RV (US/UK/UE/JP) | ninguno |
| 109 | Update Package Shipping Info | POST /fulfillment/202610/packages/{package_id}/shipping_info/update | FS Order&Fulfillment Management; Fulfillment Basic | No · RV | ninguno |
| 110 | Confirm Package Shipment (supply chain) | POST /supply_chain/202309/packages/sync | Fulfillment Basic | No (proveedor de almacén certificado) | ninguno |

### Logística (7)

| # | Nombre | Método + path | Scope (spec) | ¿Sirve al creador? | Valor |
|---|---|---|---|---|---|
| 111 | Get Shipping Providers | GET /logistics/202309/delivery_options/{delivery_option_id}/shipping_providers | FS Order&Fulfillment Management; Fulfillment Basic; Logistics Basic | No · RV | ninguno |
| 112 | Get Global Seller Warehouses | GET /logistics/202309/global_warehouses | Global Shop Information | No · RV (global) | ninguno |
| 113 | Get Warehouse List | GET /logistics/202309/warehouses | Logistics Basic | No · RV | ninguno |
| 114 | Get Warehouse Delivery Options | GET /logistics/202309/warehouses/{warehouse_id}/delivery_options | Logistics Basic | No · RV | ninguno |
| 115 | Get Shipping Template Availability | GET /logistics/202510/seller_templates | Logistics Basic | No · RV (JP/UK) | ninguno |
| 116 | Get Logistics Tracking | GET /logistics/202604/orders/{order_id}/tracking | Logistics Basic | No · RV (solo CBT) | ninguno |
| 117 | Check Shipping Template Existence | GET /logistics/202606/seller_template/template_exist | Logistics Basic | No · RV | ninguno |

### Finanzas (8)

| # | Nombre | Método + path | Scope (spec) | ¿Sirve al creador? | Valor |
|---|---|---|---|---|---|
| 118 | Get Statements | GET /finance/202309/statements | Finance Information | No · RV | ninguno |
| 119 | Get Seller Financial Transactions | GET /finance/202309/withdrawals | Finance Information | No · RV | ninguno |
| 120 | Get Transactions by Order | GET /finance/202501/orders/{order_id}/statement_transactions | Finance Information | No · RV | bajo |
| 121 | Get Transactions by Statement | GET /finance/202501/statements/{statement_id}/statement_transactions | Finance Information | No · RV | bajo |
| 122 | Get Unsettled Transactions | GET /finance/202507/orders/unsettled | Finance Information | No · RV | ninguno |
| 123 | Get Payments | GET /finance/202605/payments | Finance Information | No · RV | ninguno |
| 124 | Get TradeIn Supplier Account Balance | GET /finance/202609/account_balances | Finance Information | No · RV (TradeIn) | ninguno |
| 125 | Get TradeIn Account Transactions | GET /finance/202609/account_transactions | Finance Information | No · RV (TradeIn) | ninguno |

### Promociones (19)

| # | Nombre | Método + path | Scope (spec) | ¿Sirve al creador? | Valor |
|---|---|---|---|---|---|
| 126 | Create Promotion Activity | POST /promotion/202309/activities | Promotion Modify | No · RV | ninguno |
| 127 | Search Promotion Activities | POST /promotion/202309/activities/search | Promotion Information | No · RV | medio (cond.) |
| 128 | Get Activity | GET /promotion/202309/activities/{activity_id} | Promotion Information | No · RV | medio (cond.) |
| 129 | Update Promotion Activity | PUT /promotion/202309/activities/{activity_id} | Promotion Modify | No · RV | ninguno |
| 130 | Deactivate Activity | POST /promotion/202309/activities/{activity_id}/deactivate | Promotion Modify | No · RV | ninguno |
| 131 | Update Promotion Activity Products | PUT /promotion/202309/activities/{activity_id}/products | Promotion Modify | No · RV | ninguno |
| 132 | Remove Promotion Activity Products | DELETE /promotion/202309/activities/{activity_id}/products | Promotion Modify | No · RV | ninguno |
| 133 | Search Coupon List | POST /promotion/202406/coupons/search | Customer Service; Promotion Information | No · RV | medio (cond.) |
| 134 | Get Coupon | GET /promotion/202406/coupons/{coupon_id} | Customer Service; Promotion Information | No · RV | medio (cond.) |
| 135 | Republish Activity | POST /promotion/202607/activities/{activity_id}/republish | Promotion Modify | No · RV | ninguno |
| 136 | List Campaign Group | GET /promotion/202611/campaign_groups | Promotion Information | No · RV | bajo |
| 137 | Get Campaign Group | GET /promotion/202611/campaign_groups/{campaign_group_id} | Promotion Information | No · RV | bajo |
| 138 | List Campaign | GET /promotion/202611/campaigns | Promotion Information | No · RV | bajo |
| 139 | Get Livestream Campaign | GET /promotion/202611/livestream_campaigns/{livestream_campaign_id} | Promotion Information | No · RV | bajo |
| 140 | Get Product Campaign | GET /promotion/202611/product_campaigns/{product_campaign_id} | Promotion Information | No · RV | bajo |
| 141 | List Registered Campaign | GET /promotion/202611/registered_campaigns | Promotion Information | No · RV | bajo |
| 142 | Get Registered Campaign Counts | GET /promotion/202611/registered_campaigns/counts | Promotion Information | No · RV | ninguno |
| 143 | Get Shop Campaign | GET /promotion/202611/shop_campaigns/{shop_campaign_id} | Promotion Information | No · RV | bajo |
| 144 | Get Short Video Campaign | GET /promotion/202611/short_video_campaigns/{short_video_campaign_id} | Promotion Information | No · RV | bajo |

### Devoluciones y reembolsos (18)

| # | Nombre | Método + path | Scope (spec) | ¿Sirve al creador? | Valor |
|---|---|---|---|---|---|
| 145 | Approve Cancellation | POST /return_refund/202309/cancellations/{cancel_id}/approve | Return & Refund Basic | No · RV | ninguno |
| 146 | Reject Cancellation | POST /return_refund/202309/cancellations/{cancel_id}/reject | Return & Refund Basic | No · RV | ninguno |
| 147 | Get Reject Reasons | GET /return_refund/202309/reject_reasons | Return & Refund Basic | No · RV | ninguno |
| 148 | Approve Return | POST /return_refund/202309/returns/{return_id}/approve | Return & Refund Basic | No · RV | ninguno |
| 149 | Get Return Records | GET /return_refund/202309/returns/{return_id}/records | Return & Refund Basic | No · RV | ninguno |
| 150 | Upload Return Shipping Information | POST /return_refund/202405/returns/shipping_documents | Return & Refund Basic | No · RV | ninguno |
| 151 | Get Decision Eligibility | GET /return_refund/202601/decision_eligibility | Return & Refund Basic | No · RV | ninguno |
| 152 | Cancel Order | POST /return_refund/202602/cancellations | Return & Refund Basic | No · RV | ninguno |
| 153 | Search Cancellations | POST /return_refund/202602/cancellations/search | Return & Refund Basic | No · RV | bajo |
| 154 | Get Aftersale Eligibility | GET /return_refund/202602/orders/{order_id}/aftersale_eligibility | Return & Refund Basic | No · RV | ninguno |
| 155 | Calculate Refund | POST /return_refund/202602/refunds/calculate | Return & Refund Basic | No · RV | ninguno |
| 156 | Create Return | POST /return_refund/202602/returns | Fulfillment Basic; Return & Refund Basic | No · RV | ninguno |
| 157 | Search Returns | POST /return_refund/202602/returns/search | Return & Refund Basic | No · RV | bajo |
| 158 | Search Aftersales Requests | POST /return_refund/202603/aftersales/search | Return & Refund Basic | No · RV | bajo |
| 159 | Search Return Merchandise Authorizations | POST /return_refund/202604/rma/search | Return & Refund Basic | No · RV | ninguno |
| 160 | Reject Return | POST /return_refund/202606/returns/{return_id}/reject | Return & Refund Basic | No · RV | ninguno |
| 161 | Get Available Review Decisions | GET /return_refund/202606/review_decision | Return & Refund Basic | No · RV | ninguno |
| 162 | Review Aftersales Requests | POST /return_refund/202609/aftersales/review | Return & Refund Basic | No · RV | ninguno |

> Ojo: «Review» en 161 y 162 se refiere a revisar solicitudes de posventa. **No son reseñas de producto.**

### Optimización bajo `/seller/202611` (3) y apoyo de tienda (4)

| # | Nombre | Método + path | Scope (spec) | ¿Sirve al creador? | Valor |
|---|---|---|---|---|---|
| 163 | Get Seller Carousel Permission | GET /seller/202611/carousel_permission | Product Optimization | No · RV | ninguno |
| 164 | Upload Seller Image | POST /seller/202611/images/upload | Product Optimization | No · RV | ninguno |
| 165 | Upload Seller Materials | POST /seller/202611/materials/upload | Product Optimization | No · RV | ninguno |
| 166 | Get Authorized Shops (apoyo) | GET /authorization/202309/shops | FS Order&Fulfillment Management; Shop Authorized Information | No · RV | requisito técnico |
| 167 | Get Active Shops (apoyo) | GET /seller/202309/shops | Global Shop Information | No · RV | ninguno |
| 168 | Get Global Product Permission (apoyo) | GET /seller/202309/permissions | Global Shop Information | No · RV (global) | ninguno |
| 169 | Get Shop Group and Related Shops (apoyo) | GET /seller/202601/shop_groups | Shop Authorized Information | No · RV | ninguno |

---

## Conceptos comunes

### ¿Por qué no sirve el token de creador de Corte?

- Según `L creator-authorization-guide.txt`: «Creator authorization is different from Seller authorization. A creator token and a seller token are different credentials and must not be reused interchangeably». El error `101000` es «Wrong token identity or wrong API-token pairing».
- Casi todos los endpoints de la familia piden `shop_cipher` («Identifies the shop. Obtain it from the Get Authorized Shops API», según la spec en cada operación). El `cipher` solo viene en *Get Authorized Shops*: «Retrieves the list of shops that a seller has authorized for an app… Seller authorization is required before an app can access the data of a shop» (S, `getAuthorizedShops`).
- Los endpoints sin `shop_cipher` (los de global product, algunos de cargas y el cumplimiento de la UE) también son de vendedor; casi todos son para vendedores globales o transfronterizos.
- `user_type`: 0 = vendedor, 1 = creador, 4/5 = vendedor de Global Selling (`L authorization-overview-202407.txt`). Corte es `user_type=1`.

### ¿Solo aplican a productos de la tienda que autoriza? Sí (confirmado)

Lo que dice la documentación:
- Todo pasa por `shop_cipher` de una tienda que autorizó la app (S, todas las operaciones con `requiresShopCipher=true`).
- *Submit Product via Opportunity*: «The product must belong to the authorized shop and be in ACTIVATE status» (S).
- *Search Aftersales Requests*: «Searches aftersales requests for the authorized shop» (S/R).
- Promociones 202611: «The shop, its seller, and its region are determined from the verified authorization context» (S).
- *Search Size Charts*: «Retrieve size charts that a seller has created» (R).
- *Optimize Images*: «You will not be able to optimize any images that are not hosted by TikTok Shop» (R).
- La única operación que busca productos **por vendedor** (`seller_id`/`seller_name`) es *Search Products for Compliance Auditing* (#53). Acepta `category_asset_cipher`, que es una autorización de **partner**, y su descripción dice que entrega «the details a compliance vendor needs for testing reports». No verifiqué quién califica. No es una vía para Corte.

### Mapeo de scopes: nombre en la spec y clave de la app

La spec solo trae el **nombre visible** del scope (`x-tts-scopes`), no la clave. No encontré una fuente oficial que publique la tabla nombre→clave (`access-scope.txt` solo da los nombres). El mapeo de abajo lo **inferí** comparando nombres. Para confirmarlo hay que revisar *Partner Console → App & Service → Manage → Manage API*.

| Nombre en la spec | Clave probable en la app | Estado en la app |
|---|---|---|
| Product Basic | `seller.product.basic` | Awaiting review |
| Product Modify | `seller.product.write` | Awaiting review |
| Product Delete & Recover | `seller.product.delete` | Awaiting review |
| Product Optimization | `serller.product.optimize` (la errata viene así en la app) | Awaiting review |
| Global Product Information | `seller.global_product.info` | Awaiting review |
| Global Product Modify | `seller.global_product.write` | Awaiting review |
| Global Product Delete | `seller.global_product.delete` | Awaiting review |
| Global Category Infomation | `seller.global_product.category.info` | Awaiting review |
| Order Information | `seller.order.info` | Awaiting review |
| Fulfillment Basic | `seller.fulfillment.basic` | Awaiting review |
| Package Split And Combine | ¿`seller.fulfillment.package.write`? (no verificado) | Awaiting review |
| Update Delivery Status | `seller.delivery.status.write` | Awaiting review |
| Logistics Basic | `seller.logistics` | Awaiting review |
| Finance Information | `seller.finance.info` | Awaiting review |
| Promotion Information | `seller.promotion.info` | Awaiting review |
| Promotion Modify | `seller.promotion.write` | Awaiting review |
| Return & Refund Basic | `seller.return_refund.basic` | Awaiting review |
| Shop Authorized Information | ¿`seller.authorization.info` o `seller.shop.info`? (no verificado) | `seller.authorization.info` aprobado; `seller.shop.info` en revisión |
| Global Shop Information | ¿`seller.shop.info`? (no verificado) | Awaiting review |
| FS Order&Fulfillment Management; Read/Write External Order References; Manage Seller Redeem Info Callback; Customer Service | sin equivalente en la app | no solicitados |

- **Discrepancia:** la app tiene en revisión `seller.global_product.image_trans_task`, pero la spec dice que las tareas de traducción de imágenes (#45, #46) piden **Product Optimization**. No verifiqué si `image_trans_task` es un scope aparte o un alias.

> **[Nota del revisor, 15/11/2026]** El mapeo de arriba ya **está verificado** con el JSON oficial de docv2 (`https://partner.tiktokshop.com/api/v1/document/api_meta?src_document_id=<slug>&aid=359713&locale=en`, campo `scope_list[].scope_key`):
> - Product Basic = `seller.product.basic` (get-product-202309) · Product Modify = `seller.product.write` (update-price-202309) · Product Delete & Recover = `seller.product.delete` (delete-products-202309) · Product Optimization = `serller.product.optimize` (create-image-translation-tasks-202505).
> - Global Product Information = `seller.global_product.info` (get-global-product-202309) · Global Product Modify = `seller.global_product.write` (update-global-inventory-202309) · Global Product Delete = `seller.global_product.delete` (delete-global-products-202309) · Global Category Infomation = `seller.global_product.category.info` (get-global-categories-202309).
> - Order Information = `seller.order.info` y FS Order&Fulfillment Management = `seller.fs.order&fufillment.management` (get-order-list-202309) · Fulfillment Basic = `seller.fulfillment.basic` (search-package-202309) · **Package Split And Combine = `seller.fulfillment.package.write`** (search-combinable-packages-202309) · Update Delivery Status = `seller.delivery.status.write` (update-package-delivery-status-202309) · Logistics Basic = `seller.logistics` (get-warehouse-list-202309).
> - Finance Information = `seller.finance.info` (get-statements-202309) · Promotion Information = `seller.promotion.info` (search-promotion-activities-202309) · Promotion Modify = `seller.promotion.write` (create-promotion-activity-202309) · Return & Refund Basic = `seller.return_refund.basic` (search-returns-202602).
> - Shop Authorized Information = `seller.authorization.info` y Global Shop Information = `seller.shop.info`, ya leídos del mismo `api_meta` por la familia 04 (Get Authorized Shops y Get Active Shops).
> - **`seller.global_product.image_trans_task` queda sin endpoint verificado:** la traducción de imágenes (#45) pide `serller.product.optimize`, según su `api_meta`.
- Cuando la spec lista varios scopes para una operación (p. ej. «FS Order&Fulfillment Management; Order Information»), no indica si basta con uno. **No verificado.**

### ¿Existe algún endpoint de RESEÑAS de producto?

- **Partner API (TikTok Shop): NO.** Revisé todas las operaciones de la spec (lista `OPERATIONS` de `_meta.py`), buscando `review`, `rating`, `comment` y `feedback` en operationId y path. Solo aparecen *Review Affiliate Partner Campaign Product*, *Review a Sample Application*, *Get Available Review Decisions* y *Review Aftersales Requests*. Ninguna es de reseñas de compradores. La respuesta documentada de *Get Product* tampoco trae campos de calificación ni de reseñas (R `getproduct`).
- **Research API (developers.tiktok.com): sí existe, pero no aplica.** *Query TikTok Shop Reviews* = `POST https://open.tiktokapis.com/v2/research/tts/review/`. Pide scope `research.data.basic`, un token de cliente y el query `fields` (product_name, review_text, review_like_count, create_time, review_rating). El body lleva `product_id`, `page_start` y `page_size` (máx. 10). Su cobertura son reseñas de productos que se venden en la UE (fuente: https://developers.tiktok.com/docs/en/research-api-specs-query-tiktok-shop-reviews). Para acceder hay que ser una institución académica de EE. UU., EEE, Reino Unido, Canadá o Suiza, una organización sin fines de lucro de la UE o un caso de Brasil, y además ser «independent of commercial interests». **México no aparece** (https://developers.tiktok.com/products/research-api). En el entorno VCE existe la variante *Query TikTok Shop Reviews* (https://developers.tiktok.com/docs/en/vce-query-tiktok-shop-reviews), también solo para investigadores. **No sirve para Corte.**
- **business-api.tiktok.com:** la búsqueda no encontró ningún endpoint de reseñas. No verifiqué la documentación completa porque está fuera de esta familia.

### Qué datos de producto da cada grupo

| Grupo | Descripción | Atributos | Imágenes / video | SKU / variantes | Inventario | Guía de tallas | Reseñas |
|---|---|---|---|---|---|---|---|
| Producto local (*Get Product*, *Search Products*) | Sí: `description` HTML, `title`, `key_product_features` | Sí: `product_attributes` (id, name, values), `category_chains`, `brand` | Sí: `main_images` (uri, urls, thumb_urls, width, height), `video` (url, cover_url…), `sku_img` por variante | Sí: `skus[]` con `sales_attributes` (talla/color), `price.sale_price`, `seller_sku` | Sí: `skus[].inventory[]` por almacén | Sí: `size_chart` (image o template.id) | No |
| *Inventory Search* | No | No | No | Sí (id, seller_sku) | Sí: disponible y comprometido por almacén, más reparto `campaign_inventory`/`creator_inventory`/`in_shop_inventory` | No | No |
| *Search Size Charts* | No | No | Sí (`images[]` de la tabla) | No | No | Sí, estructurada: `table.headers/rows/cells`, `measurement_type`, `unit_system` | No |
| Global product | Sí (HTML) | Sí | Sí | Sí (precio USD/EUR, `global_quantity`) | Sí (almacén global) | Sí | No |
| Pedidos | No | No | `sku_image` | `sku_name`, precios | No | No | No |
| Devoluciones | No (solo motivo de devolución) | No | `product_image` («not yet supported» en url) | `sku_name` | No | No | No |
| Promociones | No | No | No | precios de actividad por producto/SKU | límites de cantidad | No | No |
| Optimización | Sugerencias de título y descripción, diagnósticos | diagnóstico de ATTRIBUTE / SIZE_CHART | imágenes con fondo blanco | No | No | diagnóstico | No |
| Traducción de imágenes | No | No | imagen traducida (solo idiomas de la UE) | No | No | No | No |
| Finanzas / logística / envíos | No | No | No | `sku_name`/`product_name` en transacciones | No | No | No |

---

## Fichas detalladas

Formato: **Método y path · Scope · Quién · Parámetros · Respuesta · Límites · ¿Sirve con la cuenta de creador de Corte? · Valor · Fuente**. En cada ficha, «Fuente» da el slug de D y el `operationId` de S. Cuando también usé R para el detalle, lo indico.

### A. Producto: lectura y catálogo

#### ⭐ 26. Get Product
- **Método y path:** `GET /product/202309/products/{product_id}`
- **Scope:** Product Basic (→ `seller.product.basic`, inferido; en revisión).
- **Quién:** V+SC (token de vendedor de la tienda dueña del producto).
- **Parámetros:** `product_id` (path, oblig.); `shop_cipher` (oblig.); `return_under_review_version` (bool, opc.); `return_draft_version` (bool, opc., excluyente con el anterior); `locale` (BCP-47, opc.); `query_options` (opc., `GET_PRODUCT_DETAIL_URL` agrega un deep link).
- **Respuesta (clave):** `id`, `title`, `description` (HTML), `key_product_features` (hasta 5), `product_attributes[]` (id, name, values), `category_chains[]`, `brand`, `main_images[]` (uri, urls, thumb_urls, width, height), `video` (id, url, cover_url, format, size, width, height), `size_chart` (image, template.id), `certifications`, `package_dimensions`, `package_weight`, `product_status`, `audit`, `create_time`/`update_time`, `product_detail_url`. `skus[]`: `id`, `seller_sku`, `sales_attributes[]` (id, name, value_id, value_name, `sku_img`, `supplementary_sku_images`), `price` (currency, sale_price, tax_exclusive_price, unit_price), `list_price` (solo US), `inventory[]` (quantity, warehouse_id, backorder_quantity, handling_time), `identifier_code`, `status_info`. También devuelve productos en estado `FREEZE` o `DELETED`.
- **Límites:** un producto por llamada. Las notas por región dicen que en MX el peso puede ir en gramos; `listing_quality_tier`, `list_price` y `product_families` son solo de US. No hay campos de calificación ni de reseñas.
- **¿Sirve con la cuenta de creador?** No. **Sí con requisito RV**: que la tienda dueña del producto autorice la app como vendedor. Solo cubre productos de esa tienda.
- **Valor para Corte: alto (condicionado).** Datos nuevos: la descripción completa del vendedor, los atributos (material, corte, etc.), **todas** las imágenes en alta resolución, las imágenes por variante, el video del producto, la guía de tallas, el stock por talla/color y el deep link. Hoy el creador solo ve el título, la imagen principal, el precio y la comisión (`open_collaborations/products`). Esto mejora mucho los guiones y videos UGC.
- **Fuente:** D `get-product-202309`; S `getProduct`; R `getproduct`.

#### 44. Search Products
- **Método y path:** `POST /product/202502/products/search`
- **Scope:** Product Basic · **Quién:** V+SC.
- **Parámetros:** query `shop_cipher` (oblig.), `page_size` (oblig., 1–100), `page_token`. Body (todo opcional): `status` (ALL, DRAFT, PENDING, FAILED, ACTIVATE, SELLER_DEACTIVATED, PLATFORM_DEACTIVATED, FREEZE, DELETED), `seller_skus` (máx. 10), `sku_ids` (máx. 10), `create_time_ge/le`, `update_time_ge/le`, `category_version` (v2 solo US), `listing_quality_tiers` (solo US), `listing_platforms`, `audit_status`, `sns_filter`, `return_draft_version`, `locale`, `include_live_quick_products`.
- **Respuesta:** `total_count`, `next_page_token`, `products[]` (id, title, status, `skus[]` con id, seller_sku, `price` {currency, sale_price, tax_exclusive_price}, `inventory[]` {warehouse_id, quantity}, sales_regions, create_time, update_time, audit, product_tags, selling_format…). Según la spec, «only return the key product properties».
- **Límites:** `page_size` 1–100; máximo 10,000 resultados en total.
- **¿Sirve?** No · sí con RV (solo el catálogo de la tienda que autoriza).
- **Valor:** medio (cond.). Daría el catálogo completo de una tienda socia, con precios y stock por SKU, para detectar productos nuevos que promover.
- **Fuente:** D `search-products-202502`; S `searchProducts`; R `searchproducts`.

#### 19. Inventory Search
- **Método y path:** `POST /product/202309/inventory/search`
- **Scope:** Product Basic · **Quién:** V+SC.
- **Parámetros:** body `product_ids` (máx. 100) o `sku_ids` (máx. 600; si llegan los dos, prevalece `sku_ids`).
- **Respuesta:** `inventory[]`: `product_id`, `skus[]` (id, seller_sku, `total_available_quantity`, `total_committed_quantity`, `warehouse_inventory[]` {warehouse_id, available_quantity, committed_quantity}, `total_available_inventory_distribution` {`campaign_inventory[]` (quantity, campaign_name), `creator_inventory[]` (quantity, **creator_name**), `in_shop_inventory`}).
- **Límites:** los indicados arriba.
- **¿Sirve?** No · sí con RV.
- **Valor:** medio (cond.). Daría el stock real por talla/color antes de grabar o publicar y mostraría si hay inventario **reservado para creadores** (`creator_inventory`). El endpoint de creador solo da `has_inventory`.
- **Fuente:** D `inventory-search-202309`; S `inventorySearch`; R `inventorysearch`.

#### 36. Search Size Charts
- **Método y path:** `POST /product/202407/sizecharts/search`
- **Scope:** Product Basic · **Quién:** V (en `_meta`, `requiresShopCipher=false`; R no lista `shop_cipher`). Devuelve tablas «that a seller has created».
- **Parámetros:** query `page_size` (oblig., 1–100), `page_token`, `locales`. Body: `ids` (máx. 50, tiene prioridad sobre keyword), `keyword`, `size_chart_mode` (REUSABLE_TEMPLATE o PRODUCT_SCOPED).
- **Respuesta:** `size_chart[]` (template_id, template_name, `images[]` {uri, url, locale}, related_category_ids, `size_chart_datas[]` {locale, size_chart_data: `table` (headers, rows, cells), description, is_one_size, measurement_type (GENERIC/BODY/PRODUCT_MEASUREMENTS), unit_system (METRIC/IMPERIAL), size_types}, size_chart_mode, target_regions), `next_page_token`, `total_count`.
- **¿Sirve?** No · sí con RV.
- **Valor:** medio (cond.). Daría la **guía de tallas estructurada** (tabla con medidas), que sirve para explicar el ajuste en videos de moda masculina. Complementa a `size_chart.template.id` de *Get Product*.
- **Fuente:** D `search-size-charts-202407`; S `searchSizeCharts`; R `searchsizecharts`.

#### 1. Get Brands
`GET /product/202309/brands` · **Scope:** Product Basic · **Quién:** V+SC · **Parámetros:** `page_size` (oblig., 1–100); opc. `category_id`, `is_authorized` (1 = solo autorizadas), `brand_name` (prefijo), `page_token`, `category_version` · **Respuesta:** `brands[]` (id, name, authorized_status, is_t1_brand, brand_status), `total_count`, `next_page_token` · **Límites:** paginado de 100 · **¿Sirve?** No · RV · **Valor:** bajo (metadatos de marcas de la tienda) · **Fuente:** D `get-brands-202309`; S `getBrands`.

#### 3. Get Categories
`GET /product/202309/categories` · Product Basic · V+SC · **Parámetros:** todo opcional: `locale`, `keyword`, `category_version` (v2 obligatorio en US/EU/SEA), `listing_platform`, `include_prohibited_categories` (BR, MX, EU, SEA), `is_live_quick` · **Respuesta:** `categories[]` (id, parent_id, local_name, is_leaf, permission_statuses) · **¿Sirve?** No · RV · **Valor:** bajo (Corte ya recibe `category_chains` en los productos de colaboración) · **Fuente:** D `get-categories-202309`; S `getCategories`.

#### 5. Get Category Attributes
`GET /product/202309/categories/{category_id}/attributes` · Product Basic · V+SC · **Parámetros:** `category_id` (hoja, oblig.), `locale`, `category_version` (v1 por defecto; US/EU/SEA usan v2), `is_live_quick` · **Respuesta:** `attributes[]` (id, name, type SALES_PROPERTY/PRODUCT_PROPERTY, `is_requried`, `values[]`, requirement_conditions, is_multiple_selection, metric_standards). **Solo trae metadatos de la categoría, no datos de productos.** · **¿Sirve?** No · RV · **Valor:** bajo · **Fuente:** D `get-category-attributes-202309`; S `getCategoryAttributes`; R.

#### 8. Get Category Rules
`GET /product/202309/categories/{category_id}/rules` · Product Basic · V+SC · **Parámetros:** `category_id` (hoja), `category_version`, `locale` · **Respuesta:** product_certifications, size_chart (si se exige), cod, package_dimension, epr, responsible_person, manufacturer, allowed_special_product_types, fees, seller_sku · **¿Sirve?** No · RV · **Valor:** bajo · **Fuente:** D `get-category-rules-202309`; S `getCategoryRules`.

#### 14. Get Global Product
`GET /product/202309/global_products/{global_product_id}` · Global Product Information · **Quién:** V (vendedor global/transfronterizo; `requiresShopCipher=false`) · **Parámetros:** `global_product_id` (path) · **Respuesta:** id, title, description (HTML), main_images, video.id, `skus[]` (price en USD/EUR, global_quantity, sales_attributes, sku_img, inventory por almacén global), product_attributes, brand, category, certifications, size_chart, package_*, `products[]` (region, id local, sku_mappings), global_seller_id · **Límites:** estados DRAFT/UNPUBLISHED/PUBLISHED · **¿Sirve?** No · solo con RV de un vendedor **global** · **Valor:** bajo (las tiendas mexicanas locales no usan global product; no verifiqué si alguna tienda de Corte es global) · **Fuente:** D `get-global-product-202309`; S `getGlobalProduct`; R.

#### 29. Search Global Products
`POST /product/202312/global_products/search` · Global Product Information · V · **Parámetros:** `page_size` (oblig., 1–100), `page_token`; body `status`, `seller_skus`, `create_time_ge/le`, `update_time_ge/le` · **Respuesta:** `global_products[]` (id, title, status, skus[].id/seller_sku, create_time, update_time), total_count, next_page_token · **Límites:** máximo 10,000 resultados · **¿Sirve?** No · RV (global) · **Valor:** bajo · **Fuente:** D `search-global-products-202312`; S `searchGlobalProducts`.

#### 6, 7, 10, 11. Categorías y atributos globales
- **6 Get Global Attributes** `GET /product/202309/categories/{category_id}/global_attributes`: atributos estándar para un producto global «across the seller's markets». Respuesta `attributes[]` (… required_regions, optional_regions).
- **7 Get Global Category Rules** `GET …/global_rules`: requisitos de certificaciones, size_chart, responsible_person y manufacturer por región.
- **10 Get Global Categories** `GET /product/202309/global_categories`: `categories[]`; params `locale`, `keyword`, `category_version`.
- **11 Recommend Global Categories** `POST /product/202309/global_categories/recommend`: el body de ejemplo lleva product_title, description, images y category_version; los caracteres de doble byte fallan. Respuesta `leaf_category_id`, `categories[]`.
- **Común:** scope Global Category Infomation · V (global, sin `shop_cipher`) · ¿Sirve? No · Valor: ninguno · **Fuente:** D `get-global-attributes-202309`, `get-global-category-rules-202309`, `get-global-categories-202309`, `recommend-global-categories-202309`; S.

#### 4. Recommend Category
`POST /product/202309/categories/recommend` · Product Basic · V+SC · **Parámetros:** el esquema no se ve en la spec. El ejemplo lleva `product_title`, `description`, `images`, `category_version`; opc. `locale`, `listing_platform`, `include_prohibited_categories` · **Respuesta:** `categories[]` (id, is_leaf, level, name, permission_statuses), `leaf_category_id` · **¿Sirve?** No · **Valor:** ninguno · **Fuente:** D `recommend-category-202309`; S `recommendCategory` (esquema parcial).

#### 30. Check Listing Prerequisites
`GET /product/202312/prerequisites` · Product Basic · V+SC · **Parámetros:** solo `shop_cipher` · **Respuesta:** `check_results[]` (check_item, is_failed, fail_reasons) · **¿Sirve?** No · **Valor:** ninguno · **Fuente:** D `check-listing-prerequisites-202312`; S.

#### 47, 49. Reglas y réplicas globales
- **47 Get Global Listing Rules** `GET /product/202507/global_listing_rules`, Product Basic, «Applicable only for global sellers». Respuesta `listing_methods[]`, `inventory_rules[]`.
- **49 Get Global Replicated Products** `GET /product/202507/products/{product_id}/replicated_products`, Product Basic, «Applicable only for global sellers». Respuesta `replicated_products[]` (region, shop_id, product_id, product_status).
- **Común:** V+SC · ¿Sirve? No · Valor: ninguno · **Fuente:** D `get-global-listing-rules-202507`, `get-global-replicated-products-202507`; S.

#### 53. Search Products for Compliance Auditing
`POST /product/202601/compliance/auditing/research` · Product Basic · **Quién:** no es un caso V+SC típico: `requiresShopCipher=false` y acepta `shop_cipher` **o** `category_asset_cipher` (autorización de partner) · **Parámetros:** `page_size` (oblig., 1–50), `page_token`; body `seller_id` o `seller_name` (obligatorio salvo que se manden `product_ids`), `product_ids` (tiene prioridad), `product_title`, `category_ids`, `brand_ids` · **Respuesta:** `products[]` (id, title, country, seller_id, seller_name, brand_id/brand_name, categories, listing_url), total_count, next_page_token · **¿Sirve?** No. Según su descripción es para que un «compliance vendor» prepare reportes de pruebas; no verifiqué quién califica ni en qué regiones · **Valor:** bajo / **no verificado**. Es el único endpoint que busca productos de **otros** vendedores, pero no es una vía legítima para Corte · **Fuente:** D `search-products-for-compliance-auditing-202601`; S.

#### 56, 57, 58. Oportunidades de producto
- **56 List Opportunities** `POST /product/202604/opportunities/query`: params `page_size` (≤100, por defecto 20), `page_token`, `locale`; body `opportunity_type`, `category_ids`, `create_time_ge/lt`, `tag_codes`. Respuesta `opportunities[]` (id, title, categorías, opportunity_type, create/expire_time, **search_volume**, tag_codes, reward_info).
- **57 Get Submission Records** `GET /product/202604/opportunities/submissions`: `page_size` ≤100; `status` (PENDING_REVIEW, APPROVED, REJECTED), `opportunity_id`, `product_id`, `submit_time_ge/lt`. Respuesta `submissions[]` (…, product_orders, product_pv).
- **58 Get Opportunity Detail** `GET /product/202604/opportunities/{opportunity_id}`: `opportunity` (action_type, listing_criteria, content_data, market_data, basic_info).
- **Común:** Product Basic · V+SC · ¿Sirve? No · RV · **Valor:** bajo. Son oportunidades de demanda pensadas para que la tienda publique productos, aunque `search_volume` y `market_data` podrían orientar contenido si una tienda autorizara · **Fuente:** D `list-opportunities-202604`, `get-submission-records-202604`, `get-opportunity-detail-202604`; S.

#### 61, 62, 63. SKPP
La spec no explica la sigla SKPP.
- **61 List Product SKPP Statuses** `POST /product/202606/skpps/search`: body `product_ids`, `skpp_status`, `page_size`, `page_no`; `locale`. Respuesta `products[]` (product_id, title, skpp_status, `affiliate_program_status`, total_score, target_score, rewards), total_count, update_time.
- **62 Get Shop SKPP Summary** `GET /product/202606/skpps/sum`, «available only to shops enrolled as eligible SKPP sellers». Respuesta qualified_products_count, eligible_products_count, earned_ad_credit, increased_visibility_l30d.
- **63 Get Product SKPP Detail** `GET /product/202606/skpps/{product_id}`, «available only to sellers authorized for SKPP in the US market».
- **Común:** Product Basic · V+SC · ¿Sirve? No · **Valor:** bajo (61), ninguno (62, 63: elegibilidad/US) · **Fuente:** D `list-product-skpp-statuses-202606`, `get-shop-skpp-summary-202606`, `get-product-skpp-detail-202606`; S.

### B. Producto: optimización y traducción de imágenes

#### 32. Get Product Diagnoses
`GET /product/202405/products/diagnoses` · Product Optimization · V+SC · **Parámetros:** `product_ids` (oblig., máx. 200, solo productos `ACTIVATE`) · **Respuesta:** `products[]` (id, `listing_quality` {current_tier, remaining_recommendations} solo US, `diagnoses[]` {field TITLE/DESCRIPTION/IMAGE/ATTRIBUTE/SIZE_CHART, `diagnosis_results[]` (code, how_to_solve, quality_tier), `suggestion` (seo_words, smart_texts, images)}) · **Límites:** 200 IDs; calidad de listado solo US · **¿Sirve?** No · RV · **Valor:** bajo · **Fuente:** D `get-product-diagnoses-202405`; S; R.

#### 34. Get Recommended Product Title and Description
`GET /product/202405/products/suggestions` · Product Optimization · V+SC · **Parámetros:** `product_ids` (oblig., máx. 20, `ACTIVATE`) · **Respuesta:** `products[]` (id, `suggestions[]` {field TITLE/DESCRIPTION, `items[].text`}) · **¿Sirve?** No · RV · **Valor:** bajo (textos con IA para el listado de la tienda) · **Fuente:** D `get-recommended-product-title-and-description-202405`; S; R.

#### 33. Get Products SEO Words
`GET /product/202405/products/seo_words` · Product Basic · V+SC · **Parámetros:** `product_ids` (máx. 20, `ACTIVATE`) · **Respuesta:** `products[]` (id, `seo_words[].text`) · **Límites:** «Applicable only for the US, UK, and SEA markets» → **no cubre México** · **¿Sirve?** No · **Valor:** ninguno · **Fuente:** D `get-products-seo-words-202405`; S; R.

#### 41. Diagnose and Optimize Product
`POST /product/202411/products/diagnose_optimize` · Product Optimization · V+SC · **Parámetros:** body `category_id` (hoja, oblig.); opc. `product_id` (se omite para un producto nuevo), `title` (en BR y MX, 1–300 caracteres), `description` (HTML ≤ 10,000), `brand_id`, `main_images` (≤ 9; 300–4000 px), `product_attributes`, `size_chart`, `optimization_fields` (TITLE, DESCRIPTION, IMAGE, ALL, NONE) · **Respuesta:** `listing_quality` (US), `diagnoses[]` con `suggestion` (seo_words, smart_texts, images optimizadas) · **¿Sirve?** No. Acepta contenido que todavía no se publica, pero exige el `shop_cipher` de una tienda · **Valor:** bajo · **Fuente:** D `diagnose-and-optimize-product-202411`; S; R.

#### 31. Optimize Images
`POST /product/202404/images/optimize` · Product Basic · V+SC · **Parámetros:** body `images[]` (máx. 200) con `uri` (de *Upload Product Image*) y `optimization_mode` (solo `WHITE_BACKGROUND`) · **Respuesta:** `images[]` (optimize_status SUCCESS/IGNORE/PROCESSING, optimized_uri, optimized_url, original_uri/url, width, height) · **Límites:** «You will not be able to optimize any images that are not hosted by TikTok Shop» · **¿Sirve?** No · **Valor:** bajo · **Fuente:** D `optimize-images-202404`; S; R.

#### 24. Check Product Listing
`POST /product/202309/products/listing_check` · Product Basic; Product Optimization · V+SC · **Parámetros:** el esquema no se ve (el ejemplo lleva title, category_id, skus, main_images); `is_diagnosis_required` está obsoleto · **Respuesta:** check_result, fail_reasons[], warnings, listing_quality, diagnoses[], pre_check_results[] · **¿Sirve?** No · **Valor:** ninguno · **Fuente:** D `check-product-listing-202309`; S (esquema parcial).

#### 45. Create Image Translation Tasks
`POST /product/202505/images/translation_tasks` · Product Optimization (la app también tiene `seller.global_product.image_trans_task` en revisión; ver la discrepancia arriba) · V+SC · **Parámetros:** body `images[]` (oblig.): `image_uri` (de *Upload Product Image*), `target_languages[]` · **Respuesta:** `translation_tasks[]` (image_uri, target_language, id) · **Límites:** hasta 20 combinaciones imagen×idioma por llamada y 500 tareas al día. Idiomas: cs-CZ, da-DK, de-AT, de-BE, de-DE, el-GR, en-GB, en-IE, es-ES, fi-FI, fr-FR, fr-BE, hu-HU, it-IT, nl-NL, nl-BE, pl-PL, pt-PT, sv-SE. «Applicable only for sellers that sell across EU» · **¿Sirve?** No · **Valor:** ninguno (no hay español de México ni mercado MX) · **Fuente:** D `create-image-translation-tasks-202505`; S; R.

#### 46. Get Image Translation Tasks
`GET /product/202506/images/translation_tasks` · Product Optimization · V+SC · **Parámetros:** `translation_task_ids` (opc., máx. 20) · **Respuesta:** `translation_tasks[]` (id, original_image {uri, url}, translated_image {uri, url}, target_language, status PROCESSING/COMPLETED/FAILED, fail_reason) · **Límites:** esperar 5 min después de crear la tarea; reintentar con más de 10 s entre intentos; solo UE · **¿Sirve?** No · **Valor:** ninguno · **Fuente:** D `get-image-translation-tasks-202506`; S; R.

#### 163, 164, 165. Optimización bajo `/seller/202611`
- **163 Get Seller Carousel Permission** `GET /seller/202611/carousel_permission`: respuesta `has_auto_post_permission`, `has_photo_mode_permission`.
- **164 Upload Seller Image** `POST /seller/202611/images/upload`: multipart (esquema no visible), máx. 10 MiB. Respuesta `uri`, `url`.
- **165 Upload Seller Materials** `POST /seller/202611/materials/upload`: requiere `shop_cipher`; `product_id`, `post_type`, y `materials` (ONE_PRODUCT_ONE_IMAGE) o `material_groups` (ONE_PRODUCT_MULTIPLE_IMAGES), cada material con `uri` (opc. `expire_time`, `image_description`). Respuesta material_id / image_group_id.
- **Común:** scope Product Optimization · V (163 y 164) / V+SC (165) · ¿Sirve? No · **Valor:** ninguno. Son materiales de imagen de la propia tienda para publicaciones automáticas · **Fuente:** D `get-seller-carousel-permission-202611`, `upload-seller-image-202611`, `upload-seller-materials-202611`; S.

### C. Producto: escritura, borrado y cumplimiento (ninguno aplica a Corte)

Común a todo este bloque: **Quién:** V+SC salvo donde dice V · **¿Sirve?** No (son operaciones del vendedor sobre su propio catálogo) · **Valor:** ninguno.

- **2 Create Custom Brands** `POST /product/202309/brands`: Product Basic · V · body `name` (2–30 caracteres) · máx. 50 al día y 1,000 en total · resp `id` · D `create-custom-brands-202309`.
- **9 Upload Product File** `POST /product/202309/files/upload`: Product Basic · V · multipart (esquema no visible); video entre 9:16 y 16:9 · resp id, url, name, format · D `upload-product-file-202309`.
- **12 Create Global Product** `POST /product/202309/global_products`: Global Product Modify · V · «applicable only for intra-EU sellers and global sellers» · el ejemplo lleva title, category_id, brand_id, main_images, skus, package_weight, package_dimensions; máx. 100 SKU · resp global_product_id, global_skus[] · D `create-global-product-202309`.
- **13 Delete Global Products** `DELETE /product/202309/global_products`: Global Product Delete · V · `global_product_ids` (la spec no dice el límite) · resp errors[] · D `delete-global-products-202309`.
- **15 Edit Global Product** `PUT /product/202309/global_products/{global_product_id}`: Global Product Modify · V · sobrescribe todo, incluidos los campos en blanco · resp global_skus, publish_results · D `edit-global-product-202309`.
- **16 Update Global Inventory** `POST …/{global_product_id}/inventory/update`: Global Product Modify · V · requiere Multi-Warehouse; `global_skus[]` {id, inventory[] (global_warehouse_id, quantity 0–999,999)} · D `update-global-inventory-202309`.
- **17 Publish Global Product** `POST …/{global_product_id}/publish`: Global Product Modify · V · `publish_target[]` (region, skus[] …); una publicación por mercado · resp products[], publish_result[] · D `publish-global-product-202309`.
- **18 Upload Product Image** `POST /product/202309/images/upload`: Product Basic · V · multipart (esquema no visible); no acepta URL externas · resp uri, url, height, width, use_case · D `upload-product-image-202309`.
- **20 Create Product** `POST /product/202309/products`: Product Modify · ejemplo con category_id, title, main_images, skus, save_mode, description, listing_platforms; máx. 100 SKU · resp product_id, skus[], warnings[] · D `create-product-202309`.
- **21 Delete Products** `DELETE /product/202309/products`: Product Delete & Recover · `product_ids[]` · resp errors[] · D `delete-products-202309`.
- **22 Activate Products** `POST /product/202309/products/activate` y **23 Deactivate Products** `POST …/deactivate`: Product Basic · `product_ids[]`, `listing_platforms[]` · D `activate-products-202309`, `deactivate-products-202309`.
- **25 Recover Products** `POST /product/202309/products/recover`: Product Delete & Recover · `product_ids[]` · D `recover-products-202309`.
- **27 Update Inventory** `POST /product/202309/products/{product_id}/inventory/update`: Product Modify · `skus[].id`, `inventory[]` (warehouse_id, quantity 0–999,999, backorder_quantity, handling_time), `sku_warehouse_stock_update_mode` (INCREMENTAL/FULL) · D `update-inventory-202309`.
- **28 Update Price** `POST …/{product_id}/prices/update`: Product Modify · `skus[]` (id, price, list_price, external_list_prices); solo productos ACTIVATE sin promoción en curso · D `update-price-202309`.
- **35 Create Category Upgrade Task** `POST /product/202407/products/category_upgrade_task`: Product Basic · body `{}`; migra del árbol de 3 niveles al de 7; tarda hasta 2 h · D `create-category-upgrade-task-202407`.
- **37/38/39/40/42/43 Fabricantes y personas responsables (UE)**: `POST /product/202409/compliance/manufacturers`, `POST …/manufacturers/{manufacturer_id}/partial_edit`, `POST /product/202409/compliance/responsible_persons`, `POST …/responsible_persons/{responsible_person_id}/partial_edit`, `POST /product/202501/compliance/manufacturers/search`, `POST /product/202501/compliance/responsible_persons/search` · Product Basic · V · «Target seller: Local sellers operating in EU countries» · en las búsquedas, `page_size` 1–100 · D `create-manufacturer-202409`, `partial-edit-manufacturer-202409`, `create-responsible-person-202409`, `partial-edit-responsible-person-202409`, `search-manufacturers-202501`, `search-responsible-persons-202501`.
- **48 Replicate Product** `POST /product/202507/products/{product_id}/global_replicate`: Product Modify · la descripción en la spec es un placeholder («Description of [POST]/product/:version/Replicate_Product») · solo para el método LOCAL_REPLICATION · `replicate_target[]`, `inventory_mode` · D `replicate-product-202507`.
- **50 Partial Edit Global Product** `PUT /product/202509/global_products/{global_product_id}/partial_edit`: la spec reporta el scope «Product Basic», lo cual es raro para una escritura (verificar) · V · resp global_skus, publish_results · D `partial-edit-global-product-202509`.
- **51 Edit Product** `PUT /product/202509/products/{product_id}`: Product Modify · «applicable only for active sellers/shops that have completed the KYC onboarding process»; reemplaza todo · resp product_id, skus, warnings, audit.status · D `edit-product-202509`.
- **52 Partial Edit Product** `POST /product/202509/products/{product_id}/partial_edit`: Product Modify · D `partial-edit-product-202509`.
- **54 Get Product Package Recommendations** `POST /product/202602/packages/recommend`: Product Basic · «Only available in BR and MX» · `page_size` 1–100, `product_ids` · resp products[] (abnormality_types, weight_recommendation, dimension_recommendation) · D `get-product-package-recommendations-202602`.
- **55 Submit Size Chart Appeal** `POST /product/202604/appeals/submit`: Product Basic · `product_id`, `appeal_message{…}`; máx. 50 al día · D `submit-size-chart-appeal-202604`.
- **59 Submit Product via Opportunity** `POST /product/202604/opportunities/{opportunity_id}/submit`: Product Basic · body `product_id` (debe ser de la tienda autorizada y estar ACTIVATE) · resp submission{id, status…} · D `submit-product-via-opportunity-202604`.
- **60 Create GPA Upgrade Task** `POST /product/202604/products/gpa_upgrade_task`: Product Basic · V · «only available for EU L2L sellers» · D `create-gpa-upgrade-task-202604`.
- **64 Update Stock Operation Settings** `POST /product/202608/inventory/operation/settings`: Product Basic · `seller_id`, `sku_ids` (1–500), `stock_operation_setting.enable_auto_restock` · D `update-stock-operation-settings-202608`.
- **65 Suggest Brands** `POST /product/202609/brands/suggest`: product_title, category_id, description, images → brands[] · D `suggest-brands-202609`.
- **66 Predict Product Package Dimensions and Weight** `POST /product/202609/products/package/predict`: `category_id` → package_dimensions, package_weight · D `predict-product-package-dimensions-and-weight-202609`.
- **67 Recommend Required Product Properties** `POST /product/202609/products/properties/recommend`: category_id, product_title, description, images, target_property_ids → recommended_properties[] · D `recommend-required-product-properties-202609`.
- **68 Submit Strikethrough Price** `POST /product/202609/products/{product_id}/strikethrough_price/submit`: external_product_id, skus[] (external_sku_id, external_retail_price, external_transaction_price, id); el envío vence a los 90 días · D `submit-strikethrough-price-202609`.
- **69 Create Image-Based Product Listing Task** `POST /product/202610/image_listing_tasks`: category_id, images, product_title, scene → task_id (avisa por webhook al terminar) · D `create-image-based-product-listing-task-202610`.
- **70 Get Product Property Recommendation Task** `GET /product/202610/property_recommendation_tasks/{task_id}` → recommended_properties[] · D `get-product-property-recommendation-task-202610`.
- **71 Create Size Chart V2** `POST /product/202610/size_charts`: size_chart_data, size_chart_mode, category_id, template_name → size_chart_id · D `create-size-chart-v2-202610`.
- **72 Edit Size Chart V2** `POST /product/202610/size_charts/edit`: size_chart_id, size_chart_data (opc. template_name) · D `edit-size-chart-v2-202610`.
- Todos los anteriores: **Fuente** S (operationId homónimo en camelCase).

### D. Pedidos

#### 73. Get Order List
- **Método y path:** `POST /order/202309/orders/search`
- **Scope:** FS Order&Fulfillment Management; Order Information (→ `seller.order.info`) · **Quién:** V+SC.
- **Parámetros:** query `page_size` (oblig., 1–100, por defecto 20), `sort_field` (create_time/update_time), `sort_order` (por defecto DESC), `page_token`. Body: `order_status` (UNPAID, ON_HOLD, AWAITING_SHIPMENT, PARTIALLY_SHIPPING, AWAITING_COLLECTION, IN_TRANSIT, DELIVERED, COMPLETED, CANCELLED), `create_time_ge/lt`, `update_time_ge/lt`, `shipping_type`, `buyer_user_id`, `is_buyer_request_cancel`, `warehouse_ids` (máx. 100).
- **Respuesta:** `orders[]` (id, status, create/update/paid_time, `payment` {sub_total, shipping_fee, total_amount, seller_discount, platform_discount, tax…}, `recipient_address` (**datos personales**; el teléfono va enmascarado si la logística es de la plataforma), `line_items[]` {product_id, product_name, sku_name, sku_image, sale_price, original_price, `is_sample_order`, `is_refundable_sample`, room_id…}, packages[]), total_count, next_page_token.
- **Límites:** paginado de 100. La spec no menciona la retención de datos.
- **¿Sirve?** No · RV.
- **Valor:** bajo. No trae ningún campo de afiliado, creador o `content_id` (R lo confirma), así que no se puede ligar un pedido a los videos de Corte, cosa que sí da `affiliate_creator/202410/orders/search`. Solo mostraría pedidos de muestra (`is_sample_order`) de la tienda que autorice.
- **Fuente:** D `get-order-list-202309`; S `getOrderList`; R `getorderlist`.

#### 78. Get Order Detail
`GET /order/202507/orders` · FS Order&Fulfillment Management; Order Information · V+SC · **Parámetros:** `ids` (oblig., máx. 50) · **Respuesta:** orders[] (status, payment, recipient_address [no se devuelve para UNPAID/ON_HOLD], packages[] {id, delivery_type, warehouse_id, is_sample_order}, line_items[] {product_id, product_name, sku_id, sku_name, sku_image, precios, display_status, package_status, tracking_number, is_gift…}) · **Límites:** 50 IDs por llamada · **¿Sirve?** No · RV · **Valor:** bajo (no hay campos de creador ni de comisión) · **Fuente:** D `get-order-detail-202507`; S; R.

#### 77. Get Order Price Details
`GET /order/202407/orders/{order_id}/price_detail` · Order Information · V+SC · **Respuesta:** currency, total, subtotal, deducciones del vendedor y de la plataforma, vouchers, envío, tax_amount, tax_rate, net_price_amount, `line_items` con promociones financiadas por el vendedor · **¿Sirve?** No · **Valor:** bajo · **Fuente:** D `get-order-price-details-202407`; S; R.

#### 74, 75, 76. Referencias externas de pedidos
- **74 Search Orders by External Order Reference** `POST /order/202406/orders/external_order_search`: `platform` (SHOPIFY, WOOCOMMERCE, AMAZON, ERP_SYSTEM…), `external_order_id`.
- **75 Add External Order References** `POST /order/202406/orders/external_orders`: hasta 100 pedidos.
- **76 Get External Order References** `GET /order/202406/orders/{order_id}/external_orders`: `platform`.
- **Común:** scopes Read/Write External Order References (no están en la app) · V+SC · ¿Sirve? No · **Valor:** ninguno · **Fuente:** D `search-orders-by-external-order-reference-202406`, `add-external-order-references-202406`, `get-external-order-references-202406`; S.

#### 79, 80. Cajas sorpresa y POD
- **79 Update the Blind Box Opening Results** `POST /order/202605/orders/blind_box_result/callback`: Order Information · los parámetros no se ven en la spec (el ejemplo lleva main_order_id, blind_box_results, blind_batch_box_results).
- **80 Search POD Customization Details** `POST /order/202606/pod_details/search`: Order Information · el esquema no se ve (el ejemplo lleva main_order_id y query_order_lines).
- **Común:** V+SC · ¿Sirve? No · **Valor:** ninguno · **Fuente:** D `update-the-blind-box-opening-results-202605`, `search-pod-customization-details-202606`; S (parcial).

### E. Cumplimiento y envíos

#### 91. Search Package
`POST /fulfillment/202309/packages/search` · Fulfillment Basic · V+SC · **Parámetros:** `page_size` (oblig., 1–50), `sort_field` (create_time, update_time, order_pay_time), `sort_order`, `page_token`; body `create_time_ge/lt`, `update_time_ge/lt`, `package_status` (TO_FULFILL, PROCESSING, FULFILLING, COMPLETED, CANCELLED) · **Respuesta:** packages[] (id, orders[], status, tracking_number, shipping_provider_name/id, order_line_item_ids), total_count, next_page_token · **¿Sirve?** No · RV · **Valor:** bajo · **Fuente:** D `search-package-202309`; S; R.

#### 93. Get Package Detail
`GET /fulfillment/202309/packages/{package_id}` · FS Order&Fulfillment Management, Fulfillment Basic · V+SC · **Respuesta:** package_status, sub_status, tracking_number, shipping_provider, shipping_type, handover_method, pickup_slot, **recipient_address y sender_address** (datos personales), weight, dimension, insurance (US) · **¿Sirve?** No · **Valor:** bajo · **Fuente:** D `get-package-detail-202309`; S; R.

#### 88. Get Order Tracking
`GET /fulfillment/202309/orders/{order_id}/tracking` · Logistics Basic · V+SC · **Respuesta:** `tracking[]` (description, update_time_millis, action_code) · **¿Sirve?** No · RV · **Valor:** bajo. Con autorización de la tienda permitiría seguir el envío de una muestra hacia Corte, pero solo para esa tienda · **Fuente:** D `get-order-tracking-202309`; S; R.

#### Resto del bloque de cumplimiento: operación de envío de la tienda (ninguno aplica)
Común: **Quién** V+SC (salvo donde dice V) · **¿Sirve?** No · **Valor:** ninguno · **Fuente** S + D con el slug indicado.
- **81 Search Combinable Packages** `GET /fulfillment/202309/combinable_packages/search`: Package Split And Combine · `page_size` 1–50, `order_id_list` (máx. 200) · `search-combinable-packages-202309`.
- **82 Upload Proof of Delivery File** `POST /fulfillment/202309/files/upload`: Fulfillment Basic · PDF ≤ 10 MB; «Only sellers utilizing the SOF (Seller Own Fleet) capability» · `upload-proof-of-delivery-file-202309`.
- **83 Upload Proof of Delivery Image** `POST /fulfillment/202309/images/upload`: Fulfillment Basic · JPG/PNG ≤ 5 MB · `upload-proof-of-delivery-image-202309`.
- **84 Get Order Split Attributes** `GET /fulfillment/202309/orders/split_attributes`: `order_ids` · resp split_attributes[] · `get-order-split-attributes-202309`.
- **85 Update Order Shipping Info** `POST /fulfillment/202309/orders/{order_id}/shipping_info/update`: Logistics Basic · `tracking_number`, `shipping_provider_id`; solo dentro de las 72 h posteriores al envío · `update-order-shipping-info-202309`.
- **86 Get Eligible Shipping Services** `POST …/{order_id}/shipping_services/query`: Fulfillment Basic · «in the US and JP» · `get-eligible-shipping-services-202309`.
- **87 Confirm Order Split** `POST …/{order_id}/split`: `splittable_groups(_v2)`. Para MX, la división de todas las unidades aplica a vendedores locales y la de nivel artículo a vendedores globales · `confirm-order-split-202309`.
- **89 Combine Package** `POST /fulfillment/202309/packages/combine` · `combine-package-202309`.
- **90 Update Package Delivery Status** `POST /fulfillment/202309/packages/deliver`: Update Delivery Status · «available only in the SEA region» · `update-package-delivery-status-202309`.
- **92 Batch Ship Packages** `POST /fulfillment/202309/packages/ship` · `batch-ship-packages-202309`.
- **94 Get Package Handover Time Slots** `GET /fulfillment/202309/packages/{package_id}/handover_time_slots` · `get-package-handover-time-slots-202309`.
- **95 Ship Package** `POST /fulfillment/202309/packages/{package_id}/ship` · `ship-package-202309`.
- **96 Get Package Shipping Document** `GET /fulfillment/202309/packages/{package_id}/shipping_documents`: `document_type` (oblig.), `document_size`, `document_format` (ZPL solo BR y MX) · resp doc_url · `get-package-shipping-document-202309`.
- **97 Uncombine Packages** `POST /fulfillment/202309/packages/{package_id}/uncombine`: `order_ids` · `uncombine-packages-202309`.
- **98 Create First Mile Bundle** `POST /fulfillment/202407/bundles`: V · `create-first-mile-bundle-202407`.
- **99 Upload Invoice** `POST /fulfillment/202502/invoice/upload`: «local sellers in the Brazil market» · `upload-invoice-202502`.
- **100 Check TikTok Shipping and Collection by TikTok Coverage** `GET /fulfillment/202508/tts_tracking_validation`: Logistics Basic · «only in the US Market» · `check-tiktok-shipping-and-collection-by-tiktok-coverage-202508`.
- **101 Create First Mile Bundle V2** `POST /fulfillment/202510/first_mile_bundle` · `create-first-mile-bundle-v2-202510`.
- **102 Create Packages** `POST /fulfillment/202512/packages`: «US, UK, EMEA, and JP» · `create-packages-202512`.
- **103 Submit Redemption Information** `POST /fulfillment/202601/redeem_info/callback`: Manage Seller Redeem Info Callback · `submit-redemption-information-202601`.
- **104 Get POD Customization Details** `POST /fulfillment/202606/pod_details/get`: Manage Seller Redeem Info Callback · `get-pod-customization-details-202606`.
- **105 Get Order Customs Requirements** `POST /fulfillment/202607/orders/customs_info/query`: V · `order_ids` · `get-order-customs-requirements-202607`.
- **106 Submit Customs Clearance Information** `POST /fulfillment/202607/orders/customs_info/submit`: V · `submit-customs-clearance-information-202607`.
- **107 Tracking Status Update** `POST /fulfillment/202609/order/sof/track/update`: «exclusive to the following markets: US, BR» · `tracking-status-update-202609`.
- **108 Mark Package As Shipped** `POST /fulfillment/202610/orders/{order_id}/packages`: «US, UK, ES, IE, IT, DE, FR, JP» · `mark-package-as-shipped-202610`.
- **109 Update Package Shipping Info** `POST /fulfillment/202610/packages/{package_id}/shipping_info/update` · `update-package-shipping-info-202610`.
- **110 Confirm Package Shipment** `POST /supply_chain/202309/packages/sync`: Fulfillment Basic · V · «Only warehouse service providers certified by TikTok Shop can access this API» · `confirm-package-shipment-202309`.

### F. Logística (ninguno aplica)
Común: **¿Sirve?** No · **Valor:** ninguno · **Fuente** S + D.
- **111 Get Shipping Providers** `GET /logistics/202309/delivery_options/{delivery_option_id}/shipping_providers`: `warehouse_region`, `buyer_region` · resp shipping_providers[] (id, name) · V+SC · `get-shipping-providers-202309`.
- **112 Get Global Seller Warehouses** `GET /logistics/202309/global_warehouses`: Global Shop Information · V · `get-global-seller-warehouses-202309`.
- **113 Get Warehouse List** `GET /logistics/202309/warehouses`: V+SC · resp warehouses[] (id, name, effect_status, type, sub_type, is_default, address con geolocation) · `get-warehouse-list-202309` (R).
- **114 Get Warehouse Delivery Options** `GET /logistics/202309/warehouses/{warehouse_id}/delivery_options`: `scope` (WAREHOUSE/PRODUCT) · `get-warehouse-delivery-options-202309`.
- **115 Get Shipping Template Availability** `GET /logistics/202510/seller_templates`: «only available for JP and UK market»; el body no se ve · `get-shipping-template-availability-202510`.
- **116 Get Logistics Tracking** `GET /logistics/202604/orders/{order_id}/tracking`: «supports only cross-border trade (CBT) orders» · resp logistics_details[] (newest_tracking_no, carrier_name, track_list[]) · `get-logistics-tracking-202604` (R).
- **117 Check Shipping Template Existence** `GET /logistics/202606/seller_template/template_exist`: `biz_warehouse_id` (oblig.), `shop_id` · resp template_exist · `check-shipping-template-existence-202606`.

### G. Finanzas

#### 120. Get Transactions by Order
`GET /finance/202501/orders/{order_id}/statement_transactions` · Finance Information · V+SC · **Parámetros:** `order_id` (path) · **Respuesta:** order_id, order_create_time, currency, revenue_amount, fee_and_tax_amount, shipping_cost_amount, settlement_amount, `sku_transactions[]` (sku_id, sku_name, product_name, quantity, statement_id, montos y `fee_tax_breakdown.fee` con **`affiliate_commission_amount`** «charged to the seller for payment to the creator», `affiliate_partner_commission_amount`, `affiliate_ads_commission_amount`, `affiliate_commission_deposit/release`, `cofunded_creator_bonus_amount`, `external_affiliate_marketing_fee_amount`) · **Límites:** datos desde 2023-07-01; «Applicable for all regions' sellers» · **¿Sirve?** No · RV · **Valor:** bajo. Muestra lo que la tienda paga en comisiones por SKU, pero **sin identificar al creador**. Corte ya tiene su comisión estimada y la real en la API de creador · **Fuente:** D `get-transactions-by-order-202501`; S; R.

#### 121. Get Transactions by Statement
`GET /finance/202501/statements/{statement_id}/statement_transactions` · Finance Information · V+SC · **Parámetros:** `statement_id` (path), `sort_field` (oblig., solo `order_create_time`), `sort_order`, `page_size` 1–100, `page_token` · **Respuesta:** total_settlement_amount, payable_amount, `transactions[]` (type ORDER/RESERVE/ajuste, order_id, settlement/revenue/fee_tax con los mismos campos de afiliado, reserve_*) · **Límites:** desde 2023-07-01 · **¿Sirve?** No · **Valor:** bajo · **Fuente:** D `get-transactions-by-statement-202501`; S; R.

#### Resto de finanzas (ninguno aplica)
Común: Finance Information · V+SC · **¿Sirve?** No · **Valor:** ninguno · **Fuente** S + D (R en 118, 119, 122, 123).
- **118 Get Statements** `GET /finance/202309/statements`: `sort_field` (oblig., statement_time), `statement_time_ge/lt`, `payment_status` (PAID, FAILED, PROCESSING), `page_size` 1–100 · resp statements[] (id, statement_time, settlement_amount, revenue_amount, fee_amount, adjustment_amount, payment_status, payment_id, net_sales_amount, shipping_cost_amount, payment_time) · datos desde 2023-07-01; «Applicable for all regions' sellers» · `get-statements-202309`.
- **119 Get Seller Financial Transactions** `GET /finance/202309/withdrawals`: `types` (oblig.: WITHDRAW, SETTLE, TRANSFER, REVERSE, PAYMENT, REFUND), `create_time_ge/lt`, `page_size` 1–100 · resp withdrawals[] (id, type, amount, currency, status, create_time) · `get-seller-financial-transactions-202309`.
- **122 Get Unsettled Transactions** `GET /finance/202507/orders/unsettled`: `sort_field` (oblig., order_create_time), `search_time_ge/lt`, `page_size` 1–100 · resp sumas estimadas y transactions[] (incluye `affiliate_commission_amount` estimado) · solo transacciones creadas desde 2025-01-01 · `get-unsettled-transactions-202507`.
- **123 Get Payments** `GET /finance/202605/payments`: `sort_field` (oblig., create_time), `create_time_ge/lt`, `page_size` 1–100 · resp payments[] (id, status, amount, settlement_amount, exchange_rate, paid_time, bank_account con solo los últimos 4 dígitos) · «currently unavailable to SEA markets» · `get-payments-202605`.
- **124 Get TradeIn Supplier Account Balance** `GET /finance/202609/account_balances`: `currency` (oblig.) · resp available_balance · solo TradeIn · `get-tradein-supplier-account-balance-202609`.
- **125 Get TradeIn Account Transactions** `GET /finance/202609/account_transactions`: `page_size` (oblig.), start/end_time (RFC 3339), `flow_type` · solo TradeIn · `get-tradein-account-transactions-202609`.

### H. Promociones

#### 127. Search Promotion Activities
`POST /promotion/202309/activities/search` · Promotion Information (→ `seller.promotion.info`) · V+SC · **Parámetros:** body `status` (NOT_START, ONGOING, EXPIRED, DEACTIVATED), `activity_title`, `activity_type` (FIXED_PRICE, DIRECT_DISCOUNT, FLASHSALE, SHIPPING_DISCOUNT, BUY_MORE_SAVE_MORE, GIFT_WITH_PURCHASE, BUY_X_GET_Y), `page_size` (0–100; 0 = 10), `page_token` · **Respuesta:** activities[] (id, title, activity_type, begin_time, end_time, status, product_level, discount, participation_limit), total_count, next_page_token · **Límites:** `page_token + page_size` < 10,000 · **¿Sirve?** No · RV · **Valor:** medio (cond.). Con autorización de una tienda socia, daría el calendario de ofertas relámpago y descuentos de sus productos para programar videos cuando el precio baja · **Fuente:** D `search-promotion-activities-202309`; S; R.

#### 128. Get Activity
`GET /promotion/202309/activities/{activity_id}` · Promotion Information · V+SC · **Respuesta:** activity_type, `products[]` (id, `activity_price`, discount, quantity_limit, quantity_per_user, used_quantity, `skus[]`), begin/end_time, participation_limit, status · **Límites:** no da los productos de actividades FIXED_PRICE, DIRECT_DISCOUNT o FLASHSALE que terminaron hace más de 180 días · **¿Sirve?** No · **Valor:** medio (cond.): precio de oferta por SKU · **Fuente:** D `get-activity-202309`; S; R.

#### 133. Search Coupon List
`POST /promotion/202406/coupons/search` · Customer Service; Promotion Information · V+SC · **Parámetros:** query `page_size` (1–100, por defecto 50), `page_token`; body `status`, `title_keyword`, `display_type` (REGULAR, LIVE, **CREATOR_EXCLUSIVE**, CHAT, PROMO_CODE) · **Respuesta:** coupons[] (id, title, display_type, status, claim_duration, redemption_duration, promo_code, discount, threshold, product_scope, creation_source), total_count, next_page_token · **¿Sirve?** No · RV · **Valor:** medio (cond.). La tienda socia podría mostrarle a Corte sus cupones **exclusivos para creador** («Coupons that can be claimed through the display channels of the specified creator») · **Fuente:** D `search-coupon-list-202406`; S; R.

#### 134. Get Coupon
`GET /promotion/202406/coupons/{coupon_id}` · Customer Service; Promotion Information · V+SC · **Respuesta:** coupon (display_channels, promo_code, discount {type, reduction_amount, percentage, max_discount}, threshold, product_ids, usage_limits, **usage_stats** [cupones reclamados y canjeados], live_tasks…) · **¿Sirve?** No · **Valor:** medio (cond.) · **Fuente:** D `get-coupon-202406`; S; R.

#### 136–144. Campañas de la plataforma (202611)
Notas comunes según la spec: «The shop, its seller, and its region are determined from the verified authorization context»; «Cross-shop access in the EU is limited to eligible shops belonging to the same seller». Son de solo lectura y requieren `shop_cipher`.
- **136 List Campaign Group** `GET /promotion/202611/campaign_groups`: `page_size` 1–100, `campaign_name`, `is_invited`, `only_pending_registrations`, `list_scope`, `registration_regions`, `locale` · resp campaign_groups[].
- **137 Get Campaign Group** `GET …/campaign_groups/{campaign_group_id}` · resp campaign_group (campaign_period).
- **138 List Campaign** `GET /promotion/202611/campaigns`: `campaign_group_id` (oblig.), `eligibility_filter`, `types` (product, shop, livestream, short video) · resp campaigns[].
- **139 Get Livestream Campaign** `GET …/livestream_campaigns/{livestream_campaign_id}`.
- **140 Get Product Campaign** `GET …/product_campaigns/{product_campaign_id}` · resp reglas, fees, cuotas, elegibilidad.
- **141 List Registered Campaign** `GET /promotion/202611/registered_campaigns`: `campaign_statuses`, `campaign_regions`, `types`.
- **142 Get Registered Campaign Counts** `GET …/registered_campaigns/counts` · resp all/upcoming/active/ended_count.
- **143 Get Shop Campaign** `GET …/shop_campaigns/{shop_campaign_id}`.
- **144 Get Short Video Campaign** `GET …/short_video_campaigns/{short_video_campaign_id}` · resp registration_statistics y descripción del concurso de video corto.
- **Común:** Promotion Information · V+SC · ¿Sirve? No · RV · **Valor:** bajo (142: ninguno). Son las inscripciones de la tienda a campañas de TikTok, no de creadores. Las de video corto o live podrían anticipar campañas de una tienda socia · **Fuente:** D `list-campaign-group-202611`, `get-campaign-group-202611`, `list-campaign-202611`, `get-livestream-campaign-202611`, `get-product-campaign-202611`, `list-registered-campaign-202611`, `get-registered-campaign-counts-202611`, `get-shop-campaign-202611`, `get-short-video-campaign-202611`; S (no aparecen en R).

#### Escritura de promociones (ninguno aplica)
Promotion Modify · V+SC · ¿Sirve? No · Valor: ninguno · S + D.
- **126 Create Promotion Activity** `POST /promotion/202309/activities` (title, activity_type, product_level, duration_type, begin_time, end_time) · `create-promotion-activity-202309`.
- **129 Update Promotion Activity** `PUT /promotion/202309/activities/{activity_id}` · `update-promotion-activity-202309`.
- **130 Deactivate Activity** `POST …/{activity_id}/deactivate` · `deactivate-activity-202309`.
- **131 Update Promotion Activity Products** `PUT …/{activity_id}/products` · `update-promotion-activity-products-202309`.
- **132 Remove Promotion Activity Products** `DELETE …/{activity_id}/products` · `remove-promotion-activity-products-202309`.
- **135 Republish Activity** `POST /promotion/202607/activities/{activity_id}/republish` (solo actividades que vencieron o se desactivaron en los últimos 7 días) · `republish-activity-202607`.

### I. Devoluciones y reembolsos

#### 157. Search Returns
`POST /return_refund/202602/returns/search` · Return & Refund Basic · V+SC · **Parámetros:** query `sort_field`, `sort_order`, `page_size` (10–50, por defecto 10), `page_token`; body `return_ids`, `order_ids`, `buyer_user_ids`, `return_types` (REFUND, RETURN_AND_REFUND, REPLACEMENT, EXCHANGE), `return_status` (18 valores), `arbitration_status`, `create_time_ge/lt`, `update_time_ge/lt`, `locale` · **Respuesta:** return_orders[] (order_id, return_id, return_type, return_status, `return_reason`/`return_reason_text`, `return_line_items[]` {product_name, sku_name, seller_sku, product_image}, `refund_amount`, return_tracking_number…), total_count, next_page_token · **¿Sirve?** No · RV · **Valor:** bajo. Los motivos de devolución por producto (p. ej. talla) servirían para orientar contenido, pero solo cubren a la tienda que autoriza y no se ligan al creador; R no muestra ningún campo de creador ni de muestra · **Fuente:** D `search-returns-202602`; S; R.

#### 153. Search Cancellations
`POST /return_refund/202602/cancellations/search` · Return & Refund Basic · V+SC · **Parámetros:** `page_size` 1–50, `sort_*`, `page_token`; body `cancel_ids`, `order_ids`, `buyer_user_ids`, `cancel_types`, `cancel_status`, time ranges, `locale` · **Respuesta:** cancellations[] (order_id, cancel_id, cancel_type, cancel_status, role, cancel_reason_text, refund_amount, cancel_line_items) · **¿Sirve?** No · **Valor:** bajo · **Fuente:** D `search-cancellations-202602`; S; R.

#### 158. Search Aftersales Requests
`POST /return_refund/202603/aftersales/search` · Return & Refund Basic · V+SC · «Searches aftersales requests for the authorized shop» · **Parámetros:** `whitelisted_data_fields`, `filters` (ids, statuses, return_types, time), `sort`, `pagination.page_size` (1–100), `locale` · **Respuesta:** aftersales_requests[], sku_return_requests[], total_count · **¿Sirve?** No · **Valor:** bajo · **Fuente:** D `search-aftersales-requests-202603`; S; R.

#### 149. Get Return Records
`GET /return_refund/202309/returns/{return_id}/records` · Return & Refund Basic · V+SC · **Respuesta:** records[] (event, role, description, reason_text, note, **images y videos del comprador**, create_time) · **¿Sirve?** No · **Valor:** ninguno. Trae datos y contenido del comprador que no le corresponden a Corte · **Fuente:** D `get-return-records-202309`; S; R.

#### Resto de devoluciones (ninguno aplica)
Return & Refund Basic · V+SC · ¿Sirve? No · Valor: ninguno · S + D.
- **145 Approve Cancellation** `POST /return_refund/202309/cancellations/{cancel_id}/approve` · `approve-cancellation-202309`.
- **146 Reject Cancellation** `POST …/{cancel_id}/reject` · `reject-cancellation-202309`.
- **147 Get Reject Reasons** `GET /return_refund/202309/reject_reasons` (`return_or_cancel_id`) · `get-reject-reasons-202309`.
- **148 Approve Return** `POST /return_refund/202309/returns/{return_id}/approve` · `approve-return-202309`.
- **150 Upload Return Shipping Information** `POST /return_refund/202405/returns/shipping_documents` (multipart; `return_ids`) · `upload-return-shipping-information-202405`.
- **151 Get Decision Eligibility** `GET /return_refund/202601/decision_eligibility` · `get-decision-eligibility-202601`.
- **152 Cancel Order** `POST /return_refund/202602/cancellations` (el esquema no se ve; el ejemplo lleva order_id y cancel_reason) · `cancel-order-202602`.
- **154 Get Aftersale Eligibility** `GET /return_refund/202602/orders/{order_id}/aftersale_eligibility` (el esquema de respuesta no se ve) · `get-aftersale-eligibility-202602`.
- **155 Calculate Refund** `POST /return_refund/202602/refunds/calculate` · `calculate-refund-202602`.
- **156 Create Return** `POST /return_refund/202602/returns` (Fulfillment Basic; Return & Refund Basic) · `create-return-202602`.
- **159 Search Return Merchandise Authorizations** `POST /return_refund/202604/rma/search` · `search-return-merchandise-authorizations-202604`.
- **160 Reject Return** `POST /return_refund/202606/returns/{return_id}/reject` · `reject-return-202606`.
- **161 Get Available Review Decisions** `GET /return_refund/202606/review_decision` (la descripción en la spec es un placeholder; `seller_id`, `return_or_cancel_id`) · `get-available-review-decisions-202606`.
- **162 Review Aftersales Requests** `POST /return_refund/202609/aftersales/review` · `review-aftersales-requests-202609`.

### J. Apoyo: tiendas y permisos (requisito técnico de todo lo anterior)

- **166 Get Authorized Shops** `GET /authorization/202309/shops`: FS Order&Fulfillment Management; Shop Authorized Information · token de vendedor · sin parámetros · resp `shops[]` (id, name, region, seller_type, **cipher**, code) · «Target seller: All» · **¿Sirve?** No con el token de creador · **Valor:** es un requisito técnico; sin él no hay `shop_cipher` · D `get-authorized-shops-202309`; S.
- **167 Get Active Shops** `GET /seller/202309/shops`: Global Shop Information · V · resp shops[] (id, region) · «Target seller: All», «Local sellers only have 1 shop» · Valor: ninguno · D `get-active-shops-202309`; S; R.
- **168 Get Global Product Permission** `GET /seller/202309/permissions`: Global Shop Information · V · resp permissions (MANAGE_GLOBAL_PRODUCT) · vendedores transfronterizos · Valor: ninguno · D `get-global-product-permission-202309`; S.
- **169 Get Shop Group and Related Shops** `GET /seller/202601/shop_groups`: Shop Authorized Information · V · resp shop_group_data (source, shop_group_name, shops[] {shop_id, seller_id, shop_name, shop_region}). El ejemplo muestra una tienda de US agrupada con una de MX · Valor: ninguno · D `get-shop-group-and-related-shops-202601`; S.

---

## Recomendación para Corte

1. **Con la cuenta de creador actual, ningún endpoint de esta familia sirve.** No conviene construir nada sobre ellos.
2. **Ruta de la tienda socia (opcional, a futuro):** si una tienda clave acepta autorizar la app como vendedor, lo único con valor real es la lectura de producto: ⭐ *Get Product*, más *Search Products*, *Inventory Search* y *Search Size Charts*, y como extra *Search Coupon List*/*Get Coupon* (cupones CREATOR_EXCLUSIVE) y *Search Promotion Activities*/*Get Activity* (ofertas). Bastan `Product Basic` y `Promotion Information`. Antes de intentarlo hay que verificar: (a) que TikTok apruebe esos scopes para una app de categoría «Creator collaborations»; (b) que el uso cumpla las políticas de datos (minimización; el vendedor es dueño de sus datos); (c) que el hub guarde el token de vendedor separado del de creador, como pide la guía de autorización.
3. **Sugerencia de limpieza:** retirar de la solicitud de la app los scopes de pedidos, finanzas, envíos, logística, devoluciones, global product, borrado, escritura de producto y promoción, y traducción de imágenes. No aportan datos útiles a un creador afiliado y la documentación advierte que los scopes innecesarios alargan la revisión y bajan la tasa de autorización (L `authorization-overview-202407.txt`).
4. Para conseguir más datos de producto **sin** autorización de vendedor, conviene revisar en la familia de creador `GET /affiliate_creator/202509/shop_products` (aparece en `_meta.py` de la spec). No lo verifiqué aquí porque está fuera de esta familia.

## Huecos y puntos no verificados

- **Páginas oficiales de partner.tiktokshop.com/docv2:** no se pudieron leer (se renderizan con JS). Todos los datos vienen de la spec generada a partir de esas páginas (S) y de su render por operación (R). Recomiendo descargar la doc oficial de *Get Product*, *Search Products*, *Inventory Search* y *Search Size Charts* a `research/tiktok-docs/` antes de implementar.
- ~~**Mapeo de nombre de scope a clave `seller.*`:** inferido.~~ **[Revisor]** Verificado en el `api_meta` oficial (ver la nota bajo «Mapeo de scopes»). Solo queda sin endpoint `seller.global_product.image_trans_task`.
- **Scopes múltiples:** la spec no dice si basta uno de los listados (p. ej. «FS Order&Fulfillment Management; Order Information»).
- **Endpoints con detalle parcial (20):** sus esquemas de request no se ven o la descripción es un placeholder. Son: Update the Blind Box Opening Results, Search POD Customization Details, Get Aftersale Eligibility (respuesta), Get Shipping Template Availability (body), Upload Product File, Upload Product Image, Upload Seller Image, Upload Proof of Delivery File, Upload Proof of Delivery Image, Upload Return Shipping Information, Replicate Product (placeholder), Get Available Review Decisions (placeholder), Create Product, Edit Product, Create Global Product, Edit Global Product, Check Product Listing, Recommend Category, Recommend Global Categories y Cancel Order.
- **Partial Edit Global Product:** la spec reporta el scope «Product Basic», lo cual es raro para una escritura. Verificar en la doc oficial.
- **Search Products for Compliance Auditing:** no verifiqué quién califica como «compliance vendor» ni en qué regiones aplica.
- **Disponibilidad en México:** la spec rara vez trae una línea «Target seller». Solo marqué las exclusiones explícitas (UE, US, SEA, BR, JP, UK, CBT). Que un endpoint no diga región no garantiza que funcione en MX.
- **¿Puede una app «Creator collaborations» recibir autorización de vendedor para scopes de producto y pedido?** No lo verifiqué. Que la app ya tenga aprobados `seller.affiliate_*` sugiere que acepta tokens de vendedor, pero los scopes de esta familia siguen en revisión.
- **Fuera de alcance:** FBT (`/fbt/*`), analíticas (`/analytics/*`), atención al cliente, `customer_engagement`, webhooks (p. ej. *Image Translation Completed*) y business-api.tiktok.com quedaron fuera de esta familia.

## Fuentes

- Spec OpenAPI (S): https://raw.githubusercontent.com/isaackogan/TikTok-Shop-Api-SDKs/main/.openapi/tiktok-shop.openapi.yaml (repo https://github.com/isaackogan/TikTok-Shop-Api-SDKs; `info.version 2026.11.13`).
- Lista de operaciones con `requiresShopCipher`: https://raw.githubusercontent.com/isaackogan/TikTok-Shop-Api-SDKs/main/python/src/tiktok_shop_api/generated/_meta.py
- Render por operación de la misma spec (R): https://ttspa.docs.isaackogan.com/openapi/reference/operations/ (getproduct, searchproducts, inventorysearch, searchsizecharts, getcategoryattributes, getorderlist, getorderdetail, getorderpricedetails, searchpackage, getpackagedetail, getordertracking, getlogisticstracking, getwarehouselist, getstatements, gettransactionsbyorder, gettransactionsbystatement, getunsettledtransactions, getpayments, getsellerfinancialtransactions, searchpromotionactivities, getactivity, searchcouponlist, getcoupon, searchreturns, searchcancellations, getreturnrecords, searchaftersalesrequests, createimagetranslationtasks, getimagetranslationtasks, optimizeimages, getproductdiagnoses, getrecommendedproducttitleanddescription, diagnoseandoptimizeproduct, getproductsseowords, getglobalproduct, getactiveshops).
- Doc oficial de cada endpoint (D): `https://partner.tiktokshop.com/docv2/page/<slug>` (slugs en cada ficha; vienen de `x-tts-docs-url`).
- Docs locales (L): `research\tiktok-docs\access-scope.txt`, `authorization-overview-202407.txt`, `creator-authorization-guide.txt`.
- Reseñas (Research API): https://developers.tiktok.com/docs/en/research-api-specs-query-tiktok-shop-reviews · https://developers.tiktok.com/docs/en/vce-query-tiktok-shop-reviews · elegibilidad: https://developers.tiktok.com/products/research-api
