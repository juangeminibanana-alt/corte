# Corte en Flutter

Cliente compartido para Android, Windows y web. iOS está fuera de esta entrega por decisión del propietario. El backend, las ventas, las integraciones de TikTok y el almacenamiento de Google existentes se conservan.

## Decisiones

- Diseño aprobado Contraste TikTok Shop: navegación negra, superficies blancas, coral y cian. Fuente Mona Sans local y con licencia incluida. Listas de trabajo con fotos, acciones y estados separados.
- Muestras y sus variantes recibidas no se modifican al explorar colores o tallas. La galería utiliza las fotografías devueltas por la ficha del mismo producto. Las portadas de videos deben pertenecer al mismo content_id; nunca se sustituyen por fotos del producto.
- Android y Windows usan autorización Google mediante el navegador del sistema y el broker HTTPS existente. Las credenciales permanecen en Keystore/DPAPI. La web usa Firebase Authentication y la cookie de sesión del mismo origen.
- La copia y la cola se vinculan a una identidad opaca de propietario y creador. El servidor comprueba esa vinculación antes de aplicar operaciones. Los rechazos conservan el cambio y la revisión del servidor para resolverlos.
- No se muestran reseñas ni fotos de compradores inventadas. La integración actual de Creator no proporciona esos datos.

## Compatibilidad

Android conserva `app.creatorhub`, su certificado histórico y los receptores de recordatorios anteriores. Los builds de desarrollo usan `.dev` para que una compilación sin el certificado no sustituya la instalación real. Windows conserva `CreatorHub.exe` y lee las credenciales anteriores mediante DPAPI; los archivos de datos originales no se borran. El nuevo almacenamiento local vive en una carpeta propia.

## Compilar

La revisión oficial de Flutter está fijada en `toolchain.lock.json`; el instalador verifica el commit antes de usar el SDK. Desde esta carpeta:

```text
flutter --no-version-check pub get --enforce-lockfile
flutter --no-version-check analyze --no-fatal-infos
flutter --no-version-check test
flutter --no-version-check build web --release --base-href=/flutter/ --no-web-resources-cdn --csp
node tool/bundle_web.mjs
flutter --no-version-check build apk --release
```

El bundle web utiliza la versión de Firebase fijada en `../ui/package-lock.json` y sus dependencias ya instaladas. No carga Firebase desde un CDN. La compilación Windows se realiza con `tool/package_windows.ps1` en un runner Windows estándar del repositorio público. Los avisos informativos de deprecación de Material del SDK no se convierten en errores; los errores y las advertencias del analizador sí bloquean la entrega.

## Publicación

La primera revisión se publica en `/flutter/` del sitio Firebase existente, manteniendo la aplicación publicada en la raíz y sus descargas. La política CSP de Flutter admite su motor WebAssembly sólo en esa ruta. La promoción a la raíz debe seguir a la comprobación visual y funcional con los datos reales del propietario.

No se considera validación visual una compilación correcta ni el arranque de un emulador sin pantalla. Las comprobaciones de cada entrega deben registrar por separado pruebas automáticas, compilación, revisión de interfaz y verificación en los dispositivos disponibles.
