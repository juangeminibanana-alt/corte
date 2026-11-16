# Corte en Google Cloud

Corte utiliza el sitio Firebase Hosting existente **`corte-e-book-21589`**, dentro de **`e-book-21589`**. La interfaz compilada se sirve desde `https://corte-e-book-21589.web.app`; sus rutas `/api/**`, `/img/**` y `/oauth/**` se reescriben al servicio Cloud Run `corte-gateway`. El gateway contacta por VPC al backend Python en una VM privada con un disco persistente separado. El teléfono abre la misma dirección: no necesita la PC encendida, compartir Wi-Fi ni emparejamiento.

El sitio y la aplicación web Firebase de Corte ya están registrados. **Eso no confirma una aplicación publicada y funcional.** No se ha aplicado la infraestructura de cómputo ni se han autorizado todavía sus costos. La autenticación de Google Cloud CLI sigue pendiente de completar; no se presupone acceso efectivo del CLI. No hace falta comprar un dominio ni crear otro sitio o proyecto.

La preparación y operación están en [google/README.md](google/README.md). El target de Hosting se documenta en [firebase/HOSTING.md](firebase/HOSTING.md).

## Componentes

- **Firebase Hosting:** archivos de `ui/dist` y HTTPS del sitio existente.
- **Cloud Run:** gateway sin base propia, con 1 CPU y 512 MiB, de cero a dos instancias y un timeout de 55 segundos. Su invocación pública permite los rewrites de Hosting; el backend valida la sesión del propietario antes de devolver datos privados.
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

Registra en Partner Center el callback exacto `https://corte-e-book-21589.web.app/oauth/shop`. Desde la aplicación desplegada guarda el App Secret y autoriza tu cuenta de creador. La conexión opcional de TikTok for Developers utiliza `https://corte-e-book-21589.web.app/oauth/tiktok`. Las URLs y permisos deben estar aprobados en las plataformas correspondientes antes de comprobar datos reales.

Las credenciales anteriores de Windows están ligadas a DPAPI y requieren una autorización nueva. Para migrar tu trabajo, exporta el JSON desde la aplicación anterior e impórtalo desde el navegador; no copies archivos DPAPI al servidor.

## Comprobaciones

```powershell
.\.venv-cloud\Scripts\python.exe -m unittest discover -s cloud/tests -v
terraform -chdir=cloud/google fmt -check
terraform -chdir=cloud/google init -backend=false
terraform -chdir=cloud/google validate
```

Las pruebas usan datos vacíos o sintéticos para comprobar seguridad web, propietario, cifrado, revocación aislada, Storage, proxy y persistencia. La validación estática no crea recursos ni comprueba una cuenta real de Google o TikTok. Tras publicar deben verificarse login, permisos, callbacks, sincronización y conservación de datos después de un reinicio.

Para una revisión local aislada puede usarse `CORTE_AUTH_PROVIDER=password`, un hash de contraseña y llaves temporales. `CORTE_ALLOW_HTTP=1` solo admite localhost; no se configura en la infraestructura de producción.
