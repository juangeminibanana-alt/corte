# Hosting aislado de Corte

Esta configuración publica únicamente el target `hosting:corte`, asociado al sitio
`corte-e-book-21589` dentro del proyecto `e-book-21589`. No configura ni sustituye
el Hosting predeterminado de E-BOOK. El sitio debe existir antes de publicar.
La app web de Corte registrada en Firebase es
`1:1026985150312:web:ee7a6fa15362048c6438dd`.

El frontend compilado se toma de `../../ui/dist`. Las rutas `/api/**`, `/img/**`
y `/oauth/**` pasan a Cloud Run `corte-gateway`, región `us-central1`, que a su vez
contacta al backend privado. La última regla sirve la SPA para las demás rutas.
No se fija una revisión de Run con `pinTag`: el gateway puede actualizarse de
forma independiente. El backend debe conservar rutas y parámetros originales.
[Configuración de rewrites](https://firebase.google.com/docs/hosting/full-config).

Para publicar desde esta carpeta, después de compilar y verificar el backend:

```text
npx -y firebase-tools@latest deploy --project e-book-21589 --config firebase.json --only hosting:corte
```

Ese comando no despliega Storage, reglas, Functions, Auth ni otros sitios.
`storage.rules` se conserva para el bucket separado de Corte; no debe publicarse
contra el bucket predeterminado de E-BOOK. La asociación local de Hosting sigue
el mecanismo de [targets](https://firebase.google.com/docs/hosting/multisites).

## Contrato con el gateway

- La sesión usa la cookie `__session`, con `HttpOnly`, `Secure`, `SameSite=Lax`,
  `Path=/` y sin `Domain`. Hosting elimina las otras cookies al reenviar.
- Conserva `Origin`, `X-CH-Hub`, método, cuerpo, query string y `Set-Cookie`.
  El backend recibe el host público configurado, no el nombre privado de la VM.
- Toda respuesta dinámica, incluidos errores y fotos privadas, debe incluir
  `Cache-Control: private, no-store`. El gateway no debe almacenar respuestas.
  [Cookies y caché](https://firebase.google.com/docs/hosting/manage-cache).
- Firebase Hosting corta peticiones dinámicas a los 60 segundos. La sincronización
  se inicia como tarea en segundo plano y responde pronto. El stream de eventos
  debe finalizar antes de ese límite y permitir reconexión; no debe bloquear
  solicitudes mientras se sincroniza. Ampliar el timeout de Run no elimina el
  [límite de Hosting](https://firebase.google.com/docs/hosting/cloud-run).

## Caché y acceso con Google

Los documentos, scripts públicos sin hash y configuración usan `no-store`.
Únicamente los assets con hash de Vite bajo `/assets/` reciben un año de caché
`immutable`. Los headers se comparan con la URL solicitada antes de los rewrites.
La CSP permite los scripts locales, `apis.google.com`, `www.gstatic.com`, las API
de autenticación y el iframe de `e-book-21589.firebaseapp.com`. No permite scripts
inline ni `eval`; los estilos inline siguen permitidos por los componentes.
COOP permite las ventanas de autenticación sin aislarlas de la app.

Antes de usar el sitio deben estar autorizados su dominio real en Firebase Auth y
los callbacks HTTPS de TikTok. Esta configuración no modifica providers ni dominios
autorizados del proyecto compartido. El popup es el flujo principal de Google;
el fallback por redirect requiere revisar el `authDomain` al usar un dominio
`web.app`, según las [opciones oficiales de Firebase](https://firebase.google.com/docs/auth/web/redirect-best-practices).
Cambiar `authDomain` requiere actualizar también la CSP y la URI autorizada del
provider; no es suficiente cambiar el SDK.

La existencia del sitio no confirma una publicación funcional: verifica el gateway,
el servidor y el inicio de sesión antes de publicar el frontend.
