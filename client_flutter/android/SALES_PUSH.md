# Notificaciones de ventas en Android

La aplicación de producción usa Firebase Cloud Messaging nativo. `google-services.json` se descarga del proyecto Firebase de Corte para el paquete `app.creatorhub`; se conserva fuera de Git y es obligatorio al compilar release. BoM 35.2.0 proporciona Messaging 26.0.2 y el plugin Google Services 4.6.0 genera los recursos. La variante `.dev` no registra dispositivos en Firebase de producción.

El servidor envía mensajes **data-only HIGH**, sin bloque `notification`, con `type=sale`, `event_id`, `cache_scope`, `titulo`, `texto` y `ruta=#/ventas`. El servicio no recibe credenciales de Corte. Valida permiso, configuración y scope antes de mostrar contenido. Los identificadores de evento se deduplican durante 48 horas (FCM TTL del servidor: 24 horas); la notificación usa además una identidad estable.

Canal Flutter `corte/sales`:

- `configureSales({enabled,cache_scope})` → `{enabled,permission}`. Desactivar o cambiar de cuenta cancela las notificaciones visibles de ventas y borra el scope y token del puente anterior. Sólo se conservan hashes opacos acotados durante 48 horas para evitar duplicar una notificación ya mostrada al consultar el feed tras reiniciar.
- `notificationPermission` / `requestNotificationPermission` → `concedido`, `denegado` o `no_disponible`. Se comparte el permiso existente con recordatorios.
- `pushToken` → token o `null`; sólo se devuelve con ventas habilitadas y permiso concedido. Flutter registra el token mediante su conexión autenticada.
- `showSaleNotification({id,titulo,texto,ruta,cache_scope})` → bool. Comparte validación y deduplicación con FCM; un evento duplicado válido devuelve `true`.
- `notificationLaunchRoute` → `#/ventas` o `null`; consume y valida el scope del toque.
- Callbacks sin argumentos: `pushTokenChanged` y `saleNotificationOpened`. Flutter vuelve a consultar el token o la ruta respectivamente.

No se registra ningún token ni contenido del mensaje en logs. Los recordatorios conservan sus receptores, alarmas e identificadores originales. Este componente implementa FCM para Android, no para Windows.

Las comprobaciones puras de Java de `SalesMessagePolicyTest` cubren formato, aislamiento por cuenta, identidad estable y conservación acotada del historial. La compilación Android verifica el servicio y el puente; la entrega real requiere Google Play Services, permiso concedido y un dispositivo registrado.

Referencias oficiales: [recepción de mensajes](https://firebase.google.com/docs/cloud-messaging/android/receive-messages), [cliente Android y permisos](https://firebase.google.com/docs/cloud-messaging/android/get-started).
