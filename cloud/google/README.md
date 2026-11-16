# Infraestructura de Google para Corte

## Arquitectura

```text
https://corte-e-book-21589.web.app
  Firebase Hosting: ui/dist
    /api/**, /img/**, /oauth/**
      Cloud Run: corte-gateway
        Direct VPC: 10.74.0.0/24
          VM COS privada: 10.73.0.10:8080
            Corte: backend Python + Persistent Disk
```

El sitio y la app web Firebase de Corte **ya existen** en el proyecto compartido `e-book-21589`. Reutiliza el target `hosting:corte` de `.firebaserc` en la raíz del repositorio. No crees otro proyecto, sitio o app, ni sustituyas recursos de E-BOOK. Firebase Hosting proporciona HTTPS para el dominio `web.app`; esta arquitectura no utiliza un balanceador externo, IP pública de la VM, certificado separado ni dominio comprado.

La VM usa Cloud NAT para consultar TikTok. Artifact Registry, Cloud Build, Secret Manager, Logging, snapshots y el bucket privado de Corte también permanecen en Google Cloud. El sincronizador y SQLite tienen un solo dueño: una VM y un proceso de backend.

Con `runtime_enabled=true` se crean una VM `e2-medium`, 20 GB de arranque, 20 GB de datos, snapshots, NAT y el gateway Cloud Run. El gateway tiene 1 CPU, 512 MiB, concurrencia de 8 solicitudes, mínimo cero y máximo dos instancias, y timeout de 55 segundos. Sus instancias pueden reducirse a cero; la VM de datos permanece activa. Estos servicios pueden generar cargos. No hay alta disponibilidad: mantenimiento o fallas de la VM pueden interrumpir el servicio.

## Estado y requisitos

**Publicado y verificado:** [abrir Corte](https://corte-e-book-21589.web.app). Firebase Hosting, el gateway y el backend responden por HTTPS; se comprobó el acceso real con Google del propietario, la conservación de la sesión al recargar, el cierre de sesión y una copia de seguridad creada y listada en el bucket privado. La VM reutilizó el disco de datos tras el reinicio controlado. El estado de Terraform está migrado a GCS y el plan final no propone cambios.

El usuario autorizó un presupuesto estimado de 35–40 USD al mes para uso ligero, con cargos según consumo e impuestos. La facturación del proyecto está activa. Para sincronizar datos reales de TikTok todavía debe configurarse el App Secret de la aplicación en los ajustes de Corte y autorizar la cuenta; el despliegue no incorpora credenciales de TikTok de ejemplo.

Para continuar y operar el despliegue se necesita:

- Acceso efectivo al proyecto `e-book-21589`, facturación disponible y revisión del plan y sus costos.
- Terraform >=1.9, Google Cloud CLI y Python >=3.10. El operador debe poder crear los recursos declarados, gestionar su IAM y actuar como la cuenta de build.
- La configuración pública de la app Firebase **ya registrada para Corte**, el correo/UID del propietario y Google Sign-In disponible. Preserva los proveedores y dominios autorizados existentes; cualquier incorporación debe limitarse a Corte.
- Un bucket privado dedicado cuyo nombre empiece por `corte-`. Si ya existe, usa `create_storage_bucket=false`. La creación de uno nuevo con `true` exige revisar esa acción y conservar después el mismo valor; no selecciones el bucket predeterminado de E-BOOK.

No incluyas la configuración local, planes o estado en Git, el build o la imagen. Los archivos de exclusión cubren `*.tfvars`, `*.tfstate*`, `*.tfplan` y `.terraform/`. Los valores de las dos llaves se generan fuera de Terraform y no se escriben en su estado.

## Preparar un plan revisable

Para este despliegue existente, conserva las variables privadas originales: `runtime_enabled=true`, `initialize_empty_data_disk=false` y la imagen por digest. Usa `deployment.private.tfvars.json` al generar planes de operación. El ejemplo y las fases de fundamentos siguientes documentan el aprovisionamiento inicial; no sustituyen la configuración de producción.

Desde la raíz del repositorio:

```powershell
Copy-Item cloud/google/deployment.tfvars.example cloud/google/deployment.tfvars
terraform -chdir=cloud/google init
terraform -chdir=cloud/google fmt -check
terraform -chdir=cloud/google validate
terraform -chdir=cloud/google plan -var-file=deployment.tfvars -out=foundation.tfplan
```

Completa los campos requeridos con los datos revisados del proyecto, propietario, app existente y bucket Corte. Mantén `hosting_site_id="corte-e-book-21589"`, región `us-central1` y `runtime_enabled=false` para la primera fase. El ejemplo tiene marcadores y no es una configuración lista para aplicar.

La primera fase declara APIs, cuentas de servicio, IAM, repositorio de imágenes, bucket de fuentes y contenedores vacíos de secretos. Puede incluir el bucket de datos nuevo solo cuando `create_storage_bucket=true`. Es una mutación del proyecto y debe revisarse antes de aplicar; no es una simulación sin efectos.

El estado ya se migró al backend GCS privado y versionado descrito abajo. Perder una copia local no elimina recursos. No intentes recrear recursos existentes como si fueran nuevos: utiliza el backend existente y un plan de recuperación revisado.

## Procedimiento de publicación

La siguiente secuencia describe el aprovisionamiento inicial. Las fases ya completadas se indican en el estado anterior: continúa desde el estado Terraform actual y genera planes nuevos, sin repetir la creación de recursos existentes.

1. Aplica el plan de fundamentos revisado:

   ```powershell
   terraform -chdir=cloud/google apply foundation.tfplan
   ```

2. Ejecuta `python cloud/google/manage.py secrets`. Genera dos valores aleatorios y los envía por stdin a Secret Manager, sin imprimirlos ni reemplazar llaves existentes. El runtime lee explícitamente la versión `1`; no cambies la llave maestra o su versión sin migrar la bóveda.
3. Ejecuta `python cloud/google/manage.py build --tag SHA_DEL_COMMIT_REVISADO`. Cloud Build compila el código con su cuenta propia y devuelve el digest terminado. Coloca ese valor inmutable, con `@sha256:`, en `container_image`.
4. Activa `runtime_enabled=true` y, solo para el disco **nuevo y vacío**, `initialize_empty_data_disk=true`. Genera, revisa y aplica un segundo plan:

   ```powershell
   terraform -chdir=cloud/google plan -var-file=deployment.tfvars -out=runtime.tfplan
   terraform -chdir=cloud/google apply runtime.tfplan
   python cloud/google/manage.py status
   ```

5. Comprueba el arranque de la VM y el gateway. La startup probe TCP de Cloud Run confirma únicamente que el proceso del gateway escucha; no demuestra que el backend esté disponible. Usa `/api/health` para verificar la ruta completa hasta la base del backend. En cuanto se inicialice el disco, vuelve a `initialize_empty_data_disk=false`, revisa y aplica ese cambio. No vuelvas a habilitar formateo para un disco con datos.
6. Compila y publica el frontend únicamente en el target Corte, siguiendo [HOSTING.md](../firebase/HOSTING.md). La configuración `firebase.json` de la raíz reescribe API, imágenes y callbacks a `corte-gateway` en `us-central1`; no despliegues otros targets del proyecto.
7. Verifica el sitio completo: `/api/health`, login del propietario, rechazo de una cuenta distinta, conexión a TikTok, importación y persistencia después de un reinicio controlado. Los datos reales requieren autorizar las cuentas desde la aplicación y tener aprobados los callbacks finales.

Callbacks de TikTok:

- Shop: `https://corte-e-book-21589.web.app/oauth/shop`
- Display API opcional: `https://corte-e-book-21589.web.app/oauth/tiktok`

No se necesita crear registros DNS o esperar un certificado de balanceador. La dirección existente de Hosting solo se considera funcional cuando frontend, gateway, backend y autenticación hayan sido comprobados juntos.

## Red, acceso y peticiones

La VM no tiene interfaz pública. El firewall admite su puerto 8080 únicamente desde la subred dedicada al gateway, `10.74.0.0/24`. Cloud Run llega mediante Direct VPC; no se abre acceso a las redes o servicios de E-BOOK.

La invocación pública del gateway es intencional para permitir los rewrites normales de Hosting. No concede acceso a los datos: el backend verifica la sesión Firebase del propietario. El gateway no recibe permisos de Firebase, Storage o Secret Manager; fija un único destino privado, no sigue redirects y limita cuerpos a 20 MB. Conserva `Origin` y `X-CH-Hub`, fija Host y HTTPS, e ignora los valores `Forwarded` y `X-Forwarded-*` del visitante. Reenvía un único peer observado; el backend utiliza `CORTE_PROXY_HOPS=1`.

La cookie se llama `__session`, la única que Firebase Hosting conserva al reenviar. Usa `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/` y ningún `Domain`. No se comparten cookie jars entre solicitudes. API, imágenes y errores dinámicos responden con JSON cuando corresponde y `Cache-Control: private, no-store`.

La interfaz usa polling corto: 15 segundos normalmente, 3 segundos durante sync y pausa al ocultar la pestaña. No usa SSE persistente en nube. El endpoint SSE permanece por compatibilidad; el gateway aplica una ventana de 35 segundos y lectura máxima de 17 segundos, acotando el cierre a menos de 55 segundos. Hosting limita sus rewrites dinámicos a 60 segundos. Una sincronización se inicia como tarea del backend y responde pronto; su duración no mantiene una petición abierta.

## Identidades, secretos y almacenamiento

La identidad de la VM usa ADC, con lectura y creación de sesiones Firebase, acceso a dos secretos concretos y lectura/creación de objetos solamente en el bucket Corte. No tiene permiso para editar usuarios, cambiar proveedores o cerrar sesiones globales de E-BOOK. La revocación de cookies de Corte usa su propia SQLite con huellas de cookies.

El bootstrap consulta Secret Manager desde la imagen revisada, comprueba los dos recursos exactos y la integridad de los valores, y escribe el entorno en `/run` con permisos restrictivos. No descarga una llave de cuenta de servicio. Las credenciales TikTok se cifran con AES-GCM en el disco; conserva tanto el volumen como la llave maestra.

El disco se monta y se verifica antes de iniciar Corte con systemd. Docker no reinicia el contenedor independientemente del montaje. El disco, sus snapshots diarios con retención de 14 días y el bucket Corte preservan datos; las copias de trabajo de la interfaz no sustituyen un snapshot del volumen completo.

Si el bucket Corte se registra en Cloud Storage for Firebase, mapea **solo** el target `storage:corte` al bucket dedicado antes de desplegar sus reglas. Nunca ejecutes un deploy genérico contra el bucket predeterminado de E-BOOK. Las reglas proporcionadas rechazan acceso directo de clientes; el backend usa IAM y verifica al propietario.

## Actualizar y recuperar

Construye el commit revisado, actualiza `container_image`, revisa y aplica el plan, y ejecuta `python cloud/google/manage.py restart` para que la VM cargue sus metadatos nuevos. El script detiene y arranca limpiamente la VM. El mismo plan actualiza la imagen del gateway; publica después el frontend compatible en `hosting:corte`.

`python cloud/google/manage.py status` consulta la VM y la URI del gateway; no prueba por sí solo el sitio ni el login. Los logs de aplicación y gateway excluyen query strings OAuth y se filtran los request logs de sus callbacks. Revisa Cloud Logging sin publicar datos privados.

No cambies `runtime_enabled` a `false` para apagar un servicio existente: intentaría retirar recursos protegidos. La VM, el disco, los secretos y el bucket tienen protección contra borrado. Para recuperar datos, detén la VM y utiliza un disco nuevo desde un snapshot con un plan revisado; nunca montes SQLite de escritura en dos instancias simultáneamente.

## Estado remoto y recuperación de infraestructura

El backend de [backend.tf](backend.tf) utiliza `gs://corte-e-book-21589-tfstate` con prefijo `terraform/corte`. El bucket se administra en [state.tf](state.tf): acceso uniforme, prevención de acceso público, versionado y protección contra eliminación. No tiene TTL ni políticas de retención que bloqueen la liberación de locks. No se concedieron permisos a las identidades runtime, build o gateway; no se usa el bucket de datos ni el de fuentes de compilación.

La migración conservó el lineage y los 44 identificadores de recursos; el serial avanzó una vez al escribir la copia remota. Se guardó una copia local privada antes de migrar. Una instalación nueva del operador debe usar ADC autorizado y `terraform init` contra este backend existente, sin recrear el bucket. Ejecuta después `terraform plan` con las variables privadas del despliegue y revisa cualquier diferencia antes de aplicar.

Para recuperar una versión anterior del estado, usa las generaciones privadas del objeto GCS y un procedimiento revisado con el despliegue detenido a nivel de cambios de infraestructura. No borres el estado, no fuerces locks de otro operador y no sustituyas un estado más reciente por una copia antigua sin comparar lineage, serial y recursos reales.

## Referencias oficiales

- [Firebase Hosting y Cloud Run](https://firebase.google.com/docs/hosting/cloud-run)
- [Cookies y caché de Hosting](https://firebase.google.com/docs/hosting/manage-cache)
- [Targets de Hosting](https://firebase.google.com/docs/hosting/multisites)
- [Direct VPC en Cloud Run](https://cloud.google.com/run/docs/configuring/vpc-direct-vpc)
- [Contenedores en COS](https://cloud.google.com/container-optimized-os/docs/how-to/run-container-instance)
- [Secret Manager con identidad de VM](https://cloud.google.com/secret-manager/docs/access-secret-version)
- [Sesiones Firebase](https://firebase.google.com/docs/auth/admin/manage-cookies)
