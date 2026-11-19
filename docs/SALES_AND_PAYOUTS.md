# Ventas actuales y calendario de pagos

El bloque `dashboard.actualidad` distingue tres datos: ventas de hoy, ventas de la semana natural y el calendario del próximo miércoles. No usa las ventas semanales como supuesto importe de depósito.

## Datos comprobados

[`POST /affiliate_creator/202410/orders/search`](https://partner.tiktokshop.com/docv2/page/search-creator-affiliate-orders-202410) proporciona creación y entrega del pedido, estado, cantidades, precios, comisiones estimadas y reales y actualización de cada SKU. No declara fecha de liquidación, saldo disponible para retiro, corte del depósito ni fecha prevista del abono.

Según ese contrato, `AWAITING PAYMENT` significa que el comprador todavía no ha pagado. Las ventas nuevas de `actualidad` incluyen sólo `To-SETTLE` y `SETTLED`. Los KPI históricos conservan su contrato anterior; no se reescriben sus cifras silenciosamente. Las muestras se excluyen del bloque nuevo mediante `muestras.main_order_id` y las unidades netas siguen la regla `cantidad − MAX(reembolsadas, devueltas)`, con mínimo cero.

La comisión estimada y la real son importes de la fuente. No se restan otra vez ISR, IVA o participación de agencia ni se multiplica la comisión por la cantidad de unidades. Falta de monto, moneda distinta de MXN u orden incompleta produce un total monetario `null`, sin fabricar un cero.

### Composición de la comisión: lo que el contrato no cierra

Revisado el 18/11/2026 sobre la ficha de 202410 y la de la ruta retirada 202505:

- **Shop Ads.** Según 202410, `commission_rate` es la tasa total (estándar + Shop Ads + bono + recompensa de partner) y `actual_commission` es el ingreso final, ya sin impuestos ni la parte de la agencia; eso implica que incluye Shop Ads. La ficha 202505 decía lo contrario: su `actual_commission` incluía bono y recompensa, pero no Shop Ads. Corte muestra `actual_commission` tal cual y **no le suma** `actual_shop_ads_commission`: con la definición de 202410 la duplicaría. Si valiera la de 202505, la cifra quedaría corta, no inflada.
- **Estimada contra real.** La doc no dice si `estimated_commission` descuenta impuestos o agencia. Los mosaicos «Liquidada» (real) y «Por liquidar» (estimada) van por separado, pero la cifra principal de Comisión (`Kpis.comision_total_centavos` = liquidada real + por liquidar estimada + retenida estimada) suma las dos clases. Si la estimada resultara bruta de ISR, IVA o la parte de la agencia, esa cifra mezclaría importes netos y brutos.
- **Moneda y formato.** Cada importe llega como `{amount, currency}` con `amount` en texto, sin formato documentado para MXN (símbolo, separadores, negativos). Corte solo guarda y valida la moneda de `price`. Desde la rev. 7 cada sincronización cuenta, sin guardar las respuestas, las líneas cuyo `price` trae una moneda distinta de MXN y las líneas con monedas distintas entre sus importes. Un `price` sin moneda no se cuenta: solo `dashboard.actualidad` deja su total en `null` (mientras la línea cae en hoy, la semana o lo pendiente), y los KPI históricos la suman como MXN sin ningún aviso (`resumen_json.ordenes_calidad`). Un conteo distinto de cero indica que hace falta guardar más monedas antes de confiar en las sumas.
- **Estados.** Los documentados son `UNSPECIFIED`, `AWAITING PAYMENT`, `To-SETTLE`, `SETTLED`, `REFUNDED` y `FROZEN`. Un valor distinto se guarda crudo, no cuenta como venta válida y también se cuenta en `ordenes_calidad.estados_desconocidos`.
- **Niveles.** `commission_model` y `commission_tier_setting` (otra unidad, por ejemplo «3.0 OR 5.0») no se guardan ni se convierten: deducir qué nivel se aplicó sería inventar el dato.
- Los valores de ejemplo de la ficha 202410 se contradicen entre sí (una tasa total menor que sus componentes, un bono mayor que la comisión que lo incluye, impuestos en MXN dentro de una línea en IDR). No sirven como datos de prueba ni para validar fórmulas.

### Próximo miércoles

El usuario indicó que recibe sus pagos los miércoles de madrugada. El contrato conserva ese dato como `origen_calendario: usuario`, `dia_pago: 3`, `horario: madrugada` y `fecha_programada` del miércoles próximo, inclusive el día actual si ya es miércoles. No se conoce una hora exacta.

Las [reglas oficiales mexicanas de comisión](https://seller-mx.tiktok.com/university/essay?knowledge_id=2885103953004289&lang=es-419) también describen pagos los miércoles después de liquidar los pedidos; las devoluciones o disputas pueden demorar comisiones. La [guía de pagos para creadores](https://seller-mx.tiktok.com/university/essay?knowledge_id=5003817679832849) distingue el procesamiento de la plataforma de la acreditación bancaria. Estas reglas generales no entregan el saldo ni los pedidos incluidos en el próximo pago de esta cuenta.

La [política mexicana de liquidación actualizada en abril de 2026](https://seller-mx.tiktok.com/university/essay?knowledge_id=8451160953407248) explica que el plazo depende del vendedor. Corte no conoce el plazo aplicable a cada tienda. Por tanto no proyecta un depósito añadiendo un número fijo de días a creación, entrega o actualización del pedido.

`pago_semana.monto_centavos` y `fecha_prevista` permanecen `null`, con `estado: no_disponible`. `fecha_programada` es únicamente calendario. `pendiente.comision_por_liquidar_centavos` representa las comisiones conocidas en `To-SETTLE`, de todas las fechas, y se muestra por separado. Las comisiones retenidas y las asociadas a pedidos sin pagar también se separan.

### API retirada

El [aviso oficial de migración](https://partner.tiktokshop.com/docv2/page/si5r1bv3) retiró `POST /affiliate_creator/202505/orders/trace/search` globalmente el 15 de agosto de 2026. Su antigua metadata aún menciona filtros como `SETTLE_TIME`, pero el sustituto 202410 sólo filtra por creación. No basar una integración nueva ni una conciliación de pago semanal en esa ruta retirada. El código histórico de trazas no constituye prueba de disponibilidad vigente.

## Hora local, caché y verificación

- Hoy usa `America/Mexico_City` (UTC−6), no el día UTC del servidor.
- La semana estadística va de lunes a domingo y sólo cuenta pedidos creados hasta el instante de la lectura.
- El resumen es independiente del período histórico seleccionado y aparece tanto en el dashboard normal como en los dashboard `30d` y `todo` del snapshot.
- El ETag del snapshot incluye la fecha mexicana de su propio `generado_at`, además de las versiones. Se renueva al cruzar medianoche aunque no haya cambios de datos, para evitar mostrar las ventas de ayer como las de hoy.
- Las pruebas sintéticas cubren pagos y estados, exclusión de muestras, múltiples líneas del mismo pedido, medianoche y cambio de semana, valores ausentes, impuestos, devoluciones, calendario de miércoles y caché diaria. No son una verificación de depósito bancario.
