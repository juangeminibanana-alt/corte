# Corte en Google Cloud

Corte utiliza el sitio Firebase Hosting existente **`corte-e-book-21589`**, dentro de **`e-book-21589`**. La interfaz compilada se sirve desde `https://corte-e-book-21589.web.app`; sus rutas `/api/**`, `/img/**` y `/oauth/**` se reescriben al servicio Cloud Run `corte-gateway`. El gateway contacta por VPC al backend Python en una VM privada con un disco persistente separado. El teléfono abre la misma dirección: no necesita la PC encendida, compartir Wi-Fi ni emparejamiento.

**Publicado y verificado:** [abrir Corte](https://corte-e-book-21589.web.app). Hosting y el backend responden por HTTPS; se comprobaron el acceso real del propietario con Google, el cierre de sesión, el rechazo de API sin sesión y la creación y consulta de un respaldo privado desde la interfaz. También se revisó la vista móvil. La VM se reinició conservando el disco existente, con el permiso de formateo desactivado. El costo autorizado es un estimado de 35–40 USD al mes para uso ligero, más variaciones por consumo e impuestos.

La conexión de TikTok Shop se recuperó desde la configuración del panel anterior y se renovó mediante el servicio de TikTok. El perfil real quedó verificado y la sincronización automática consulta muestras, productos, pedidos y vitrina correctamente. Las claves y la autorización renovada se conservaron tras reiniciar la VM. No se publicaron datos de demostración ni credenciales.

La preparación y operación están en [google/README.md](google/README.md). El target de Hosting se documenta en [firebase/HOSTING.md](firebase/HOSTING.md).

## Componentes

- **Firebase Hosting:** archivos de `ui/dist` y HTTPS del sitio existente.
- **Cloud Run:** gateway sin base propia, con 1 CPU y 512 MiB, de cero a dos instancias y un timeout de 55 segundos. Su invocación pública permite los rewrites de Hosting; el backend valida la sesión del propietario antes de devolver datos privados. La startup probe TCP comprueba que el proceso escucha; `/api/health` sigue siendo la comprobación completa de conectividad con el backend y disponibilidad de su base.
- **Compute Engine:** una VM COS privada en `10.73.0.10:8080`. Conserva el sincronizador, la analítica y las reglas de muestras existentes; Cloud NAT permite sus consultas salientes a TikTok.
- **Persistent Disk:** SQLite, imágenes, revocaciones de sesión y bóvedas cifradas en `/var/lib/corte`. Solo un proceso Gunicorn controla el planificador y las renovaciones de TikTok.
- **Servicios de Google:** Artifact Registry y Cloud Build para la imagen, Secret Manager para dos llaves, Cloud Logging y snapshots del disco. Firebase Auth gestiona el acceso con Google y un bucket privado exclusivo de Corte contiene los respaldos.

La interfaz en nube consulta los cambios cada 15 segundos, o cada 3 segundos durante una sincronización, y pausa esas consultas al ocultar la pestaña. No mantiene SSE activo en nube. El endpoint SSE se conserva por compatibilidad y el gateway limita su duración por debajo del timeout de Run y del límite de Hosting.

## Proyecto compartido

Corte usa recursos propios con prefijo `corte-` dentro de `e-book-21589`. No reemplaza el Hosting, bucket, reglas, usuarios ni configuración de E-BOOK. La configuración pública de la app Corte se mantiene fuera de Git; no debe copiarse el bucket predeterminado de E-BOOK al despliegue.

Firebase Admin usa **Application Default Credentials** de la identidad de la VM, sin una llave de cuenta de servicio descargada. La VM puede leer usuarios y crear cookies de sesión; no puede modificar usuarios o la configuración global de Firebase. Cerrar sesión registra localmente la huella de la cookie de Corte y no revoca sesiones de otras aplicaciones del proyecto.

## Acceso y datos

Firebase Google exige un token del proyecto, proveedor Google, correo verificado, propietario autorizado y autenticación reciente. La cookie del servidor se llama **`__session`**, dura 12 horas y usa `Secure`, `HttpOnly`, `SameSite=Lax` y `Path=/`, sin atributo `Domain`. Hosting elimina otras cookies al reenviar al servicio. Las mutaciones conservan la comprobación del origen público exacto y `X-CH-Hub: 1`.

El gateway fija el destino privado, el Host público y HTTPS; conserva `Origin` para validar CSRF y reemplaza los encabezados de proxy entrantes por un único peer observado. El backend confía en ese único salto. API, fotos y errores dinámicos usan `Cache-Control: private, no-store`.

Las dos llaves se leen de versiones concretas de Secret Manager y se colocan temporalmente en `/run` con permisos restrictivos. Sus valores no se incluyen en Terraform, metadatos, imágenes, argumentos de comandos ni registros. AES-GCM protege las credenciales de TikTok; cambiar la llave maestra sin migrar la bóveda impide descifrarla.

El disco tiene snapshots diarios con retención de 14 días. Las copias de **Configuración → Privacidad y datos** contienen planes, notas, avisos, recordatorios, plantillas y preferencias, sin tokens ni App Secrets. Importar fusiona datos mediante las reglas existentes. Ventas, muestras y métricas vuelven a sincronizarse con TikTok. Estas copias no reemplazan el snapshot completo del volumen.

## Conectar TikTok y migrar

Si ya tienes el `config.json` del panel anterior, usa **Configuración → TikTok Shop → Importar conexión anterior**. Corte recibe solo los campos de conexión por HTTPS, los valida y los guarda en su bóveda cifrada. La importación exige un destino sin autorización activa y la misma identidad si ya quedaba una cuenta guardada. Consulta el perfil real de TikTok antes de iniciar la sincronización; una falla de verificación se informa sin afirmar que la cuenta quedó conectada. El archivo original se conserva y sus valores nunca se devuelven en la respuesta.

Para una conexión nueva configura juntos el **App Key y el App Secret de la misma app**; la nube no completa la clave con la aplicación fija del repositorio. Después autoriza tu cuenta de creador. Para cambiar de app con una autorización activa, desconecta primero la cuenta; guardar las claves conserva los datos existentes.

Registra en Partner Center el callback exacto `https://corte-e-book-21589.web.app/oauth/shop` para las autorizaciones nuevas. La conexión opcional de TikTok for Developers utiliza `https://corte-e-book-21589.web.app/oauth/tiktok`. Las URLs y permisos deben estar aprobados en las plataformas correspondientes.

Los archivos DPAPI de Windows están cifrados para el perfil local y no deben copiarse directamente al servidor. La importación de conexión JSON es independiente de las copias de tu plan, avisos y notas; estas últimas se importan desde **Privacidad y datos** y no contienen credenciales.

## Comprobaciones

```powershell
.\.venv-cloud\Scripts\python.exe -m unittest discover -s cloud/tests -v
terraform -chdir=cloud/google fmt -check
terraform -chdir=cloud/google init -backend=false
terraform -chdir=cloud/google validate
```

Las pruebas usan datos vacíos o sintéticos para comprobar seguridad web, propietario, cifrado, revocación aislada, Storage, proxy y persistencia. La validación estática no crea recursos ni comprueba una cuenta real de Google o TikTok. Tras publicar deben verificarse login, permisos, callbacks, sincronización y conservación de datos después de un reinicio.

Para una revisión local aislada puede usarse `CORTE_AUTH_PROVIDER=password`, un hash de contraseña y llaves temporales. `CORTE_ALLOW_HTTP=1` solo admite localhost; no se configura en la infraestructura de producción.

## Windows y Android con Google Cloud

La versión 1.1.0 conserva los clientes instalables: Windows usa su ejecutable, WebView2, bandeja, archivos y DPAPI; Android mantiene su APK, WebView con assets empaquetados, recordatorios y Android Keystore. Sus transportes nativos consultan el servidor de Google por HTTPS. No necesitan emparejar el teléfono con una PC ni mantenerla encendida. La interfaz instalada no navega a la web remota.

Al pulsar **Continuar con Google**, la aplicación abre el navegador habitual. El propietario comprueba el código y aprueba ese dispositivo; el acceso dura hasta 30 días y puede revocarse. Las credenciales permanecen en la capa nativa, fuera de JavaScript. El protocolo y la validación de identidad se documentan en [NATIVE_CLIENTS.md](NATIVE_CLIENTS.md).

Los clientes conservan información consultada y una cola durable de cambios con identificadores idempotentes. La copia sin conexión cubre los datos descargados; no equivale a una descarga de todo el histórico. Windows conserva una copia de la SQLite anterior y Android archiva su copia y operaciones antes de recuperar la organización. Las importaciones nativas comprueban la cuenta de TikTok dentro del bloqueo que protege la mutación.

Los paquetes se generan con `scripts/build_windows.ps1` y `scripts/build_android.ps1`. Windows entrega un ZIP con `CreatorHub.exe`, `_internal` e **Instalar Corte.cmd**. Android entrega un APK release sin depuración, conservando el certificado de la aplicación anterior para permitir actualizarla. Ese certificado histórico de desarrollo no representa una publicación en Google Play. Las guardas de empaquetado verifican que no se distribuyan credenciales, datos privados ni fixtures.

Descargas 1.1.0 publicadas en Firebase Hosting: [Windows](https://corte-e-book-21589.web.app/descargas/Corte-Windows-1.1.0.zip), [Android](https://corte-e-book-21589.web.app/descargas/Corte-Android-1.1.0.apk) y [SHA256](https://corte-e-book-21589.web.app/descargas/SHA256SUMS.txt). Se verificaron los bytes y hashes de ambas descargas después de publicarlas. Los pasos de instalación y el alcance de la verificación están en [LEEME.txt](https://corte-e-book-21589.web.app/descargas/LEEME.txt).
