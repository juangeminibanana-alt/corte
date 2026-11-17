"""Regla de imágenes versionadas C45 (BUILD_SPEC §6.3.3), evaluada en SQL sobre la tabla `imagenes` DENTRO de la
transacción de lectura de cada respuesta:

- `estado = 'ok'` y versión de 8 hex  -> '/img/<t>/<id>?v=<versión>' + entrada en `meta_imagenes` (w, h, lqip, color);
- fila con `url_origen` y otro estado -> '/img/<t>/<id>?v=0' sin entrada en `meta_imagenes`;
- sin fila o sin URL de origen        -> None (la interfaz pinta el mosaico).

Nunca se usa sha1(url) como versión. Las claves son 'p:<product_id>' y 'a:cuenta'.
Rev. 4 (15/11): 'g:<product_id>-<n>' (galería de vitrina) y 'm:<product_id>' (producto parecido) siguen la MISMA regla,
pero no se cargan todas de golpe (pueden ser miles): `cargar(claves)` trae solo las de la ficha que se está armando.
Rev. 5 (15/11): 'v:<video_id>' = portada del video que da la Display API (antes reservada, C4); también por `cargar()`.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any, Iterable

# La regla completa vive en esta consulta: la URL sale ya armada (o NULL) y `con_meta` dice si lleva meta_imagenes.
_SQL_COLUMNAS_C45 = """
SELECT img_key,
       CASE WHEN estado = 'ok' AND length(version) = 8 AND version NOT GLOB '*[^0-9a-f]*'
                 THEN '/img/' || tipo || '/' || ref_id || '?v=' || version
            WHEN url_origen IS NOT NULL AND trim(url_origen) <> ''
                 THEN '/img/' || tipo || '/' || ref_id || '?v=0'
       END                                                                                   AS url,
       (estado = 'ok' AND length(version) = 8 AND version NOT GLOB '*[^0-9a-f]*')            AS con_meta,
       ancho, alto, lqip, color
FROM imagenes
"""
SQL_REGLA_C45 = _SQL_COLUMNAS_C45 + "WHERE tipo IN ('p', 'a')\n"
_REF_VALIDA = re.compile(r'^(?:\d{1,25}|cuenta)$')
_REF_DIFERIDA = {'g': re.compile(r'^\d{1,25}-(?:\d|1[01])$'), 'm': re.compile(r'^\d{1,25}$'),
                 'v': re.compile(r'^\d{1,25}$'),
                 'e': re.compile(r'^[0-9]{1,25}-[0-9a-f]{16}$')}
_PREFIJOS_POR_CLAVE = ('g:', 'm:', 'v:', 'e:')


class ResolutorImagenes:
    """Carga la regla C45 una sola vez por transacción y responde URL + meta por clave."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._urls: dict[str, str | None] = {}
        self._meta: dict[str, dict[str, Any]] = {}
        self._agregar(conn.execute(SQL_REGLA_C45).fetchall())

    def _agregar(self, filas: Iterable[Any]) -> None:
        for img_key, url, con_meta, ancho, alto, lqip, color in filas:
            self._urls[img_key] = url
            if url and con_meta:
                self._meta[url] = {'w': int(ancho or 0), 'h': int(alto or 0), 'lqip': lqip or None, 'color': color or None}

    @staticmethod
    def _valida(tipo: str, ref: str) -> bool:
        if tipo in ('p', 'a'):
            return _REF_VALIDA.match(ref) is not None
        patron = _REF_DIFERIDA.get(tipo)
        return patron is not None and patron.match(ref) is not None

    def cargar(self, claves: Iterable[str]) -> None:
        """Rev. 4: trae (en la MISMA transacción) la regla C45 de estas claves 'g:'/'m:' (las 'p:'/'a:' ya están)."""
        pedidas = sorted({c for c in claves if c not in self._urls and c[:2] in _PREFIJOS_POR_CLAVE})
        for i in range(0, len(pedidas), 500):
            trozo = pedidas[i:i + 500]
            marcas = ','.join('?' * len(trozo))
            self._agregar(self._conn.execute(f'{_SQL_COLUMNAS_C45} WHERE img_key IN ({marcas})', trozo).fetchall())
            for c in trozo:
                self._urls.setdefault(c, None)

    def url(self, tipo: str, ref_id: Any) -> str | None:
        """URL versionada (o '?v=0', o None) de la imagen `tipo:ref_id`. Las 'g'/'m' se cargan con `cargar()`."""
        if ref_id is None:
            return None
        ref = str(ref_id)
        if not self._valida(tipo, ref):
            return None
        clave = f'{tipo}:{ref}'
        if tipo in _REF_DIFERIDA and clave not in self._urls:
            self.cargar([clave])
        return self._urls.get(clave)

    def producto(self, product_id: Any) -> str | None:
        return self.url('p', product_id)

    def avatar(self) -> str | None:
        return self.url('a', 'cuenta')

    def meta_de(self, urls: Iterable[str]) -> dict[str, dict[str, Any]]:
        return {u: dict(self._meta[u]) for u in urls if u in self._meta}

    def meta_para(self, respuesta: Any) -> dict[str, dict[str, Any]]:
        """MetaImagenes de una respuesta: recorre el objeto y toma solo las URLs '/img/…' que trae (y que tienen meta)."""
        vistas: set[str] = set()
        pila = [respuesta]
        while pila:
            x = pila.pop()
            if isinstance(x, dict):
                pila.extend(x.values())
            elif isinstance(x, list):
                pila.extend(x)
            elif isinstance(x, str) and x.startswith('/img/') and x in self._meta:
                vistas.add(x)
        return {u: dict(self._meta[u]) for u in sorted(vistas)}

    def con_version(self, url: str | None) -> bool:
        return bool(url) and url in self._meta
