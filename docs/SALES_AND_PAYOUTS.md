# Ventas actuales y calendario de pagos

El bloque `dashboard.actualidad` distingue tres datos: ventas de hoy, ventas de la semana natural y el calendario del próximo miércoles. No usa las ventas semanales como supuesto importe de depósito.

## Datos comprobados

[`POST /affiliate_creator/202410/orders/search`](https://partner.tiktokshop.com/docv2/page/search-creator-affiliate-orders-202410) proporciona creación y entrega del pedido, estado, cantidades, precios, comisiones estimadas y reales y actualización de cada SKU. No declara fecha de liquidación, saldo disponible para retiro, corte del depósito ni fecha prevista del abono.

Según ese contrato, `AWAITING PAYMENT` significa que el comprador todavía no ha pagado. Las ventas nuevas de `actualidad` incluyen sólo `To-SETTLE` y `SETTLED`. Los KPI históricos conservan su contrato anterior; no se reescriben sus cifras silenciosamente. Las muestras se excluyen del bloque nuevo mediante `muestras.main_order_id` y las unidades netas siguen la regla `cantidad − MAX(reembolsadas, devueltas)`, con mínimo cero.

La comisión estimada y la real son importes de la fuente. No se restan otra vez ISR, IVA o participación de agencia ni se multiplica la comisión por la cantidad de unidades. Falta de monto, moneda distinta de MXN u orden incompleta produce un total monetario `null`, sin fabricar un cero.

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
