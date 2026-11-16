# Fuentes de respaldo web

Copias sin modificar de las fuentes que solicita el motor de Flutter 3.50.0
(engine 371f77202a). Las rutas conservan los nombres y versiones de Google Fonts:

- Noto Color Emoji v39: los diez subconjuntos 0–9, con licencia SIL OFL 1.1.
- Noto Sans Symbols 2 v25: los seis subconjuntos, con licencia SIL OFL 1.1.
- Roboto v32: respaldo básico de CanvasKit, con licencia Apache 2.0.

Los archivos originales se obtuvieron de `https://fonts.gstatic.com/s/`.
Las licencias completas están en `licenses/`; `sources.json` registra cada URL,
tamaño y SHA-256. No se han cambiado los datos, las tablas ni los nombres internos.

El bootstrap usa `fontFallbackBaseUrl` relativo a la base del sitio. Para el
despliegue de Corte en `/flutter/`, las peticiones se resuelven en
`/flutter/fonts/<ruta original>`, dentro del mismo origen. Estas fuentes se
cargan sólo cuando Flutter las necesita; no se añaden a los binarios nativos.
