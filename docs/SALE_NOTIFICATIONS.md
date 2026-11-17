# Avisos de nuevas ventas

Corte 2.3 incorpora alertas de venta para sus dispositivos Android y Windows autorizados. Se activan en **Ajustes → Avisos de ventas**. El permiso del sistema se solicita mediante esa acción; no al abrir Corte.

## Origen y tiempos

Se avisa por cada producto de un pedido que TikTok reporta pagado (`To-SETTLE` o `SETTLED`), con sus unidades netas, importe y comisión estimada si la fuente los informa. No se avisa por muestras, pedidos sin pagar, reembolsados ni registros incompletos. Una transición conocida de pedido sin pagar a pagado puede producir un aviso.

El primer registro establece una referencia de las ventas existentes para no enviar el historial. Las posteriores se identifican por dispositivo, creador, pedido y producto. Las actualizaciones repetidas, reinicios y refrescos del token conservan esa referencia.

El trabajador de Google revisa los pedidos confirmados en la base cada 15 segundos. Esto **no significa que TikTok informe la compra en 15 segundos**: los datos llegan mediante la sincronización configurada de Corte, además de cualquier retraso de TikTok. La conexión Creator actual no ofrece un webhook documentado de nueva venta. La configuración de producción recomendada para estos avisos es sincronización automática cada 15 minutos.

## Entrega

- **Android:** Firebase Cloud Messaging, datos de prioridad alta con vencimiento de 24 horas. El servicio nativo valida el creador y el permiso antes de mostrar un aviso, incluso con Flutter cerrado. Forzar la detención desde Android o bloquear las notificaciones impide la entrega. Un registro opaco de eventos evita repetir el mensaje al abrir la aplicación y consultar la copia en Google.
- **Windows:** Corte consulta sus eventos privados en Google y muestra notificaciones del sistema. Con los avisos activados, cerrar la ventana conserva el proceso en la bandeja; el menú **Salir de Corte** lo termina y detiene la recepción. Windows puede silenciar los avisos según sus ajustes de concentración. Abrir otra vez el acceso directo recupera la misma instancia.
- **Web:** muestra los datos compartidos y el resumen de ventas; esta entrega no registra suscripciones push de navegador.

No se garantiza recepción inmediata ni entrega exactamente una vez ante fallos de red o del sistema operativo. Se conservan eventos y confirmaciones en Google, con deduplicación adicional en los clientes.

## Aislamiento y configuración

Los endpoints `/api/push/register`, `/status`, `/events` y `/ack` requieren autenticación nativa y `X-Corte-Cache-Scope` vigente. El servidor determina el propietario y el dispositivo; no los acepta del cuerpo. El token FCM se cifra en el disco privado de Google y nunca aparece en respuestas de estado ni registros. Cambiar de creador, revocar el dispositivo o cerrar sesión detiene la entrega del contexto anterior.

FCM usa la credencial ADC existente, sin descargar claves privadas. El rol de ejecución recibe únicamente `cloudmessaging.messages.create` para enviar mensajes. Android usa el paquete histórico `app.creatorhub` y conserva su certificado de actualización. La configuración pública del proyecto se obtiene con Firebase CLI en `client_flutter/android/app/google-services.json`; no se incluye en Git. Los paquetes `.dev` de CI no registran push de producción y la compilación release exige la configuración real.

Las pruebas de servidor y cliente usan ventas sintéticas. No se insertan ventas de prueba en la cuenta real ni se mandan notificaciones de prueba automáticamente.
