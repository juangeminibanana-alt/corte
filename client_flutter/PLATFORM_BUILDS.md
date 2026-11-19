# Compilaciones de Corte Flutter

La configuración fija Flutter **3.50.0**, commit oficial `ab2912035e160d9cad6306df307576da6128ebdb`, en `toolchain.lock.json`. `tool/bootstrap_flutter.py` descarga únicamente esa revisión del repositorio oficial y comprueba el commit; si encuentra otro SDK en la ruta, falla sin modificarlo. `pubspec.lock` debe estar guardado antes de ejecutar CI.

El workflow `.github/workflows/corte-flutter-builds.yml` admite inicio manual para Windows, Android o web. Como GitHub exige que `workflow_dispatch` exista en la rama por defecto, la revisión inicial usa un disparador acotado: sólo las ramas `codex/tiktok-shop-firebase-cloud` y `claude/corte-nube-trabajo`, sólo cambios de `client_flutter/**` o del propio workflow y sólo compilación Windows. No se mezcla con `main` para activar CI; nuevos pushes cancelan la compilación anterior de esa revisión. Android y web conservan inicio manual.

Usa las acciones oficiales de GitHub fijadas por commit, permisos de lectura, runners estándar y retención de artefactos de un día. No instala secretos, no publica en Hosting ni tiendas y no usa runners de pago. El repositorio fue verificado público; el workflow se omite si pasa a privado. Las cuotas de almacenamiento de Actions siguen correspondiendo a la cuenta.

El análisis conserva errores y advertencias como fallos. Los avisos informativos no bloquean (`--no-fatal-infos`): Flutter 3.50 informa la futura migración de Material a un paquete separado; no se ha introducido una dependencia no comprobada para silenciarlo.

## Windows

`tool/package_windows.ps1` compila el runner nativo y empaqueta `CreatorHub.exe` junto con sus DLL y la carpeta `data`. El ejecutable aislado no contiene todo el runtime. El nombre técnico permite mantener la continuidad con la instalación histórica; el producto visible es Corte. El artefacto de CI incluye un informe SHA-256 junto al ZIP. No altera la instalación ni los datos existentes.

Esta computadora no tiene Visual Studio C++/Windows SDK detectables. El runner estándar `windows-2025` se usa para compilar; no se instalará aquí un workload de varios GB sin espacio suficiente.

Los datos históricos deben conservarse en `%LOCALAPPDATA%\CreatorHub`: SQLite en `datos\hub.sqlite`, bóveda de dispositivo en `secretos\dispositivo_nube.dpapi`, configuración y caché. Flutter debe usar su propio subdirectorio y migrar mediante copia, sin abrir ese SQLite como una base Flutter vacía ni sobrescribir la bóveda. La credencial DPAPI sólo puede descifrarse en la cuenta Windows original, con la entropía `Corte/dispositivo-nube/v1`; no se incorpora a binarios ni a Git.

## Android

La actualización de producción conserva **`app.creatorhub`**, el certificado histórico y un `versionCode` superior. La clave privada no entra al repositorio ni al workflow. El certificado esperado se comprueba contra `android/firma_esperada.txt`; una firma generada en CI no puede actualizar esa app sin desinstalarla. Por eso el job de CI produce exclusivamente una compilación de desarrollo `.dev`, identificada como tal. El release de actualización se firma localmente con la clave histórica existente.

Con el mismo ID y certificado Android conserva el sandbox y el Keystore, pero la nueva implementación debe leer sus formatos antes de sustituir funcionalidad:

- Keystore `creatorhub.emparejamiento.v1`; preferencias cifradas `creatorhub_seguro`, AES-GCM con AAD igual al nombre del valor. Entradas `corte.nube.dispositivo.v1`, `corte.nube.autorizacion.v1` y `corte.nube.propietario.v1`.
- Copia `files/copia/snapshot.json.gz` y `meta.json`; imágenes `files/img`; cambios pendientes `files/cola/ops.jsonl`; respaldo de migración `files/anterior_nube`.
- Recordatorios históricos y receptores de alarmas/arranque deben permanecer disponibles hasta completar la migración. No se borran datos ni preferencias al actualizar.

## iOS

Suspendido por indicación explícita del usuario. No hay plataforma iOS generada, jobs macOS, configuración de firma ni cambios en una cuenta Apple. La lógica Dart puede mantenerse portable para una decisión futura.

## Fuentes oficiales consultadas

- [Archivo y versiones oficiales de Flutter](https://docs.flutter.dev/install/archive).
- [Herramientas de Windows: Visual Studio y workload C++](https://docs.flutter.dev/platform-integration/windows/setup).
- [Compilar y distribuir iOS: Xcode, firma y Apple Developer](https://docs.flutter.dev/deployment/ios).
- [Runners estándar de GitHub y repositorios públicos](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).
- [Releases de checkout](https://github.com/actions/checkout/releases), [upload-artifact](https://github.com/actions/upload-artifact/releases) y [setup-java](https://github.com/actions/setup-java/releases).

Preparar estos archivos no inicia una ejecución de CI ni publica una aplicación. La validación de cada plataforma se registra cuando su compilación y sus pruebas se hayan ejecutado realmente.
