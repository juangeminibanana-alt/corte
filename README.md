# Corte

Corte mantiene sus **aplicaciones nativas de Windows y Android**, conectadas a Google Cloud, además de una versión web privada. La interfaz compartida usa navegación negra, contenido claro y acentos coral y cian inspirados en TikTok Shop. El modo nube funciona por HTTPS sin emparejar el teléfono con una PC.

**Versión publicada:** [Abrir Corte](https://corte-e-book-21589.web.app). El acceso con Google está limitado al propietario. En Configuración puedes recuperar una conexión anterior desde su JSON o configurar la pareja App Key y App Secret de tu app de TikTok Shop.

**Aplicaciones 1.1.2:** [Android APK](https://corte-e-book-21589.web.app/descargas/Corte-Android-1.1.2.apk) · [Windows ZIP](https://corte-e-book-21589.web.app/descargas/Corte-Windows-1.1.2.zip). Android actualiza la instalación anterior con la misma firma; Windows incluye `CreatorHub.exe`, `_internal` y `Instalar Corte.cmd`.

- **Inicio simplificado:** resultados, hasta cinco prioridades y accesos directos. El detalle permanece en Muestras, Tiendas, Ventas, Videos y Productos.
- **Muestras y productos:** lista con fotos reales, filtros y acciones; ficha con galería completa, variante recibida y opciones disponibles para solicitar muestras. La copia sin conexión conserva las fichas consultadas y precarga sus imágenes ya descargadas.
- **Google con Firebase Authentication:** el servidor verifica la identidad y limita el acceso al propietario autorizado.
- **Firebase Storage:** copias privadas del trabajo local, con importación y restauración desde Configuración.
- **Publicación en Google:** Firebase Hosting sirve la interfaz por HTTPS; Cloud Run la conecta con el backend privado de Compute Engine y su disco persistente. Conserva la sincronización de TikTok y la analítica existentes.

La configuración, los requisitos y la publicación están en [Corte en la nube](cloud/README.md). Firebase Authentication y Storage comparten el proyecto de Google Cloud donde se ejecuta el backend Python. El repositorio por sí solo no activa estos servicios.

El [inventario de API y sus límites](docs/API_COVERAGE.md) distingue lo que obtiene la autorización de creador de las API que requieren una tienda de vendedor. La [tabla de tallas, las reseñas y las fotos de compradores por producto](docs/PRODUCT_SIZE_CHARTS_AND_REVIEWS.md) son requisitos pendientes de una fuente de datos aplicable; aún no están implementados. La [dirección visual elegida](ui/DESIGN.md) documenta composición, accesibilidad y diferencias intencionales respecto de los conceptos.

## Desarrollo de la versión web

Requisitos: Node 24, pnpm 11.25 y Python 3.12. Instala las dependencias del frontend y compílalo:

```powershell
cd ui
pnpm install --frozen-lockfile
pnpm build
```

El frontend se sirve desde el mismo origen que la API; la configuración pública de Firebase llega desde el servidor. Los secretos de administración y TikTok permanecen fuera del navegador y de Git. Las pruebas nuevas de la versión web no dependen de datos personales:

```powershell
python -m pip install -r cloud/requirements.txt
python -m unittest discover -s cloud/tests -v
```

## Aplicaciones de escritorio y Android

Corte es un hub de Windows y una app de Android para **creadores afiliados de TikTok Shop**. Junta en un solo lugar las
muestras que pediste (y los videos que debes), tus ventas y comisiones, las tiendas, los productos y los videos, y te
ayuda a ponerte al día con las tiendas.

- **Windows** (`CreatorHub.exe`): conserva el shell nativo y el hub Python con su archivo local. Al conectar Google,
  trabaja con el servidor de la nube y conserva una copia para consultar sin conexión. El archivo previo permanece
  separado; la sincronización de TikTok se ejecuta en Google para evitar renovar las mismas credenciales desde dos equipos.
- **Android**: mantiene Java, WebView con interfaz incluida en el APK, Keystore, copia local, operaciones pendientes y
  recordatorios. Se conecta al mismo servidor por HTTPS con autorización de Google; no carga una web remota en su WebView.
- **Servidor de Google**: sincroniza la **API oficial de Affiliate Creator** de TikTok Shop y la **Display API**
  conectada para portadas y métricas reales de videos. Las credenciales permanecen cifradas en el servidor.

La arquitectura original de red local sigue disponible para instalaciones que la utilicen. El modo nube usa una
conexión distinta y conserva el historial local sin exigir que el teléfono y Windows estén en la misma red.

Solo usa endpoints de lectura de las API oficiales.

## Estructura

| Carpeta | Qué contiene |
| --- | --- |
| `hub/` | Hub en Python 3.12: sincronizador, base local, API local para la interfaz, bóveda de credenciales, emparejamiento LAN y `CreatorHub.spec` (PyInstaller). |
| `ui/` | Interfaz en React + TypeScript + Vite. La misma compilación se usa en Windows (pywebview) y en Android (WebView). |
| `android/` | App de Android en Java, sin dependencias externas (Gradle). Copia `ui/dist` a sus assets al compilar. |
| `scripts/` | Compilación y utilidades: `build_windows.ps1`, `build_android.ps1`, `preparar_entorno.ps1`, `dev.ps1`, etc. |
| `instalador/` | `Instalar.ps1`, `Instalar Corte.cmd` y `desinstalar.ps1` (instalación por usuario, sin administrador). `CreatorHub.iss` es opcional (Inno Setup). |
| `spec/contrato.ts` | Contrato de tipos entre el hub y la interfaz (respuestas de la API local). |
| `spec/ui_firmas/` | Firmas de los módulos de la interfaz (`@/datos`, `@/dominio`, `@/componentes`…). |
| `spec/assets/`, `branding/` | Íconos maestros (SVG) y los PNG/ICO que se generan a partir de ellos. |
| `tools/` | Guardia del ejecutable, generador de licencias de terceros y del `.ico`. |
| `research/catalogo_endpoints/` | Catálogo comentado de los endpoints de TikTok que se evaluaron. |

## Cómo compilar

Requisitos (Windows 10/11 x64):

- **Python 3.12** (con el lanzador `py`).
- **Node 24** (portátil sirve).
- Para Android: **JDK 17**, **Android SDK** (platform y build-tools 35) y **Gradle 8.11**.

Los scripts traen rutas fijas de la cadena de herramientas (por ejemplo `D:\android-toolchain\...` y `D:\Android\Sdk`).
Ajústalas a tu equipo en `scripts/comun.ps1` (Node) y `scripts/build_android.ps1` (Gradle, JDK y SDK).

**Windows** (crea `.venv-hub`, instala `node_modules`, compila la interfaz, empaqueta con PyInstaller, revisa el
ejecutable con la guardia y corre una autoprueba):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
```

Deja `dist\CreatorHub-<versión>-windows.zip` con la carpeta del programa, `Instalar.ps1` e `Instalar Corte.cmd`.

**Android** (compila la interfaz y el APK de release):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_android.ps1 -Online
```

Deja `dist\CreatorHub-<versión>.apk`. La primera vez usa `-Online` para que Gradle llene su caché; después compila sin
internet. El release se firma con la llave de depuración de tu equipo (`%USERPROFILE%\.android\debug.keystore`; si no
existe, Android Studio la crea al compilar cualquier proyecto, o puedes generarla con `keytool`). Por eso un APK
compilado por ti no puede actualizar uno instalado desde Releases (habría que desinstalarlo antes). En este repositorio
solo compila el tipo `release`: el código de depuración (`-Tipo debug`) no se publica.

La versión de ambos sale de `version.json`.

## Cómo instalar desde Releases

1. En la página de **Releases** descarga `CreatorHub-<versión>-windows.zip` y, si quieres la app del teléfono,
   `CreatorHub-<versión>.apk`.
2. **Windows:** descomprime todo el zip y da doble clic en `Instalar Corte.cmd`. Instala por usuario en
   `%LOCALAPPDATA%\Programs\CreatorHub`, sin permisos de administrador, y crea los accesos directos. Para actualizar,
   repite con el zip nuevo. Se desinstala desde Configuración de Windows › Aplicaciones.
3. **Android:** copia el APK al teléfono, permite instalar apps de origen desconocido e instálalo. Con el teléfono y la
   PC en la misma red Wi-Fi, empareja desde la app con el código de emparejamiento que muestra Corte en Windows.

La primera vez, Corte te guía para conectar tu cuenta de TikTok Shop (necesitas el App Secret de tu app de Partner
Center) y, de forma opcional, la Display API.

## Privacidad: qué no está en este repositorio

Corte se desarrolló con los datos reales de una cuenta. Para no publicarlos, **este repositorio no incluye** las
pruebas automáticas, los fixtures, las galerías de desarrollo, los ejemplos de verificación ni los documentos de diseño
que usan esos datos. Por eso:

- `npm test` (en `ui/`) y las pruebas del hub no funcionan tal cual: faltan los archivos de prueba y su configuración.
- El modo demo con fixtures (`npm run dev:demo`, `scripts/dev.ps1` con su fuente por omisión) y las galerías
  `#/dev/...` quedan vacíos o fallan. El modo demo del ejecutable (`CreatorHub.exe --demo`) sí funciona: usa datos
  sintéticos que vienen en `hub/creatorhub/demo/`.
- `scripts/verificar_todo.ps1`, `scripts/probar_empaquetado.ps1`, `android/jdk/correr.ps1` y
  `android/verificar_codigo.ps1` dependen de material no publicado.

La compilación de producción (`build_windows.ps1` y `build_android.ps1` en release) no depende de nada de eso.
