# Corte 2.0 · entrega Flutter

Nueva aplicación compartida para Android, Windows y web. La web está publicada en [Corte Flutter](https://corte-e-book-21589.web.app/flutter/#/muestras); la aplicación anterior sigue disponible en la raíz. El backend, las integraciones y los datos existentes permanecen en Firebase y Google Cloud. iOS queda aplazado por indicación del propietario.

## Paquetes publicados

| Plataforma | Archivo | Tamaño | Procedencia |
|---|---|---:|---|
| Android | [Corte-Android-2.0.0.apk](https://corte-e-book-21589.web.app/descargas/Corte-Android-2.0.0.apk) | 57,150,972 bytes | `426a30c` |
| Windows x64 | [Corte-Windows-2.0.0.zip](https://corte-e-book-21589.web.app/descargas/Corte-Windows-2.0.0.zip) | 14,335,863 bytes | `e01204f` |

En Windows hay que descomprimir el paquete completo y abrir `CreatorHub.exe`; la carpeta `data` y las DLL forman parte de la aplicación. Android conserva `app.creatorhub` y su certificado histórico para actualizar la instalación anterior. No se publicaron aplicaciones en tiendas.

Huellas SHA-256 verificadas descargando los archivos publicados:

```text
Android FE3C9FC4DF8C0854381E97CC8E7F21ECC34C8A6BF22D06765880DA9942ADC774
Windows 35A2FDF27DE975B16E8D0EFE259022E639B73CF7E08494A42A333A32B3D511D3
```

El [manifiesto de descarga](https://corte-e-book-21589.web.app/descargas/Corte-2.0.0.json) conserva tamaños, rutas y procedencia. Los paquetes versionados anteriores permanecen disponibles.

## Validación realizada

- 77 pruebas de Flutter aprobadas: autenticación, transporte, copia y cola, imágenes, planificación, formularios, conflictos, historial del navegador y tamaños de pantalla.
- 118 pruebas del backend aprobadas. El despliegue `5519910` cambió únicamente las referencias de las dos imágenes existentes; el plan final de Terraform no contiene cambios pendientes.
- Web revisada con los datos reales del propietario en teléfono y escritorio: 104 muestras, 33 pendientes, galería de nueve fotos, colores/tallas y portadas de videos. Abrir y cancelar formularios no modificó datos de negocio. Atrás actualiza la pantalla y conserva el historial.
- Android: actualización en emulador mediante `install -r -t`, conservando UID, directorio de datos y fecha de instalación original. Paquete Release sin `debuggable`, con R8, tres ABI y firma V2 histórica. El primer arranque superó el límite de 14 segundos; después se comprobó la actividad reanudada, ventana dibujada y ausencia de errores fatales/Flutter. La segunda apertura reutilizó esa instancia y devolvió `Status ok`.
- Windows: compilación remota real en runner estándar, paquete PE x64/AOT, runtime y CRT completos, icono correcto y ZIP íntegro. El arranque nativo mostró la pantalla de acceso a Google. La sesión autenticada y las fotografías no se comprobaron dentro del ejecutable nativo.

No se verificó un teléfono físico ni se aprobaron nuevas autorizaciones de dispositivos durante estas comprobaciones. Las notificaciones del sistema Windows todavía no tienen proveedor nativo; los recordatorios y su gestión están disponibles en la aplicación. La integración actual de Creator no proporciona reseñas ni fotografías de compradores; no se sustituyeron por imágenes de producto.

## Compilación Android en Windows

El SDK de Flutter 3.50 debe regenerar el registrante para Release después de ejecutar pruebas. Una primera compilación con un registrante de desarrollo y `--no-pub` puede conservar `IntegrationTestPlugin` en Android. No se deben ejecutar pruebas y compilaciones de la misma carpeta en paralelo.

Si Windows no tiene habilitados enlaces simbólicos para herramientas de desarrollo, se puede deshabilitar sólo esa plataforma para el proceso de compilación Android, sin modificar la configuración del sistema:

```powershell
$previousFlutterWindows = $env:FLUTTER_WINDOWS
try {
  $env:FLUTTER_WINDOWS = 'false'
  flutter --no-version-check build apk --release
} finally {
  $env:FLUTTER_WINDOWS = $previousFlutterWindows
}
```

AGP 9.3.2 resuelve el fallo de lint con Java 17 de 9.3.1. Kotlin se compila sin caché incremental para evitar el error al cerrar cachés entre el proyecto en C: y las dependencias en D:. Lint, R8 y la comprobación del certificado permanecen activos.
