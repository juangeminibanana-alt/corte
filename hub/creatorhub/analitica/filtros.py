"""Validación de la query cruda de las lecturas de analítica contra LISTAS BLANCAS (03 §6.2, BUILD §5).

Cada lectura acepta solo sus parámetros; un parámetro desconocido o un valor fuera de la lista blanca da
ErrorDominio('parametros_invalidos', …, http=400). Los valores que terminan en ORDER BY o IN (`orden`, `granularidad`,
`grupo`, `clase`, `estado`) nunca se interpolan: se traducen con diccionarios fijos o se pasan como parámetros.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Any, Mapping

from ..errores import ErrorDominio
from . import reglas

_FECHA = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_PERIODO_MES = re.compile(r'^(\d{4})-(\d{2})$')
_ID_NUMERICO = re.compile(r'^\d{1,25}$')
_ID_MUESTRA = re.compile(r'^[0-9A-Za-z_-]{1,64}$')
_CONTROL = re.compile(r'[\x00-\x1f\x7f]')


def invalido(mensaje: str, parametro: str | None = None) -> ErrorDominio:
    return ErrorDominio('parametros_invalidos', mensaje, http=400,
                        detalle={'parametro': parametro} if parametro else None)


def no_encontrado(mensaje: str, detalle: Mapping[str, Any] | None = None) -> ErrorDominio:
    return ErrorDominio('no_encontrado', mensaje, http=404, detalle=dict(detalle) if detalle else None)


def _texto(filtros: Mapping[str, Any], clave: str) -> str | None:
    v = filtros.get(clave)
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        if len(v) != 1:
            raise invalido(f'El parámetro «{clave}» viene repetido.', clave)
        v = v[0]
    if isinstance(v, bool):
        v = '1' if v else '0'
    s = str(v).strip()
    return s if s != '' else None


def solo_permitidos(filtros: Mapping[str, Any] | None, permitidos: tuple[str, ...]) -> dict[str, Any]:
    f = dict(filtros or {})
    sobran = sorted(k for k in f if k not in permitidos)
    if sobran:
        raise invalido(f'Parámetro no válido: «{sobran[0]}».', sobran[0])
    return f


def fecha(filtros: Mapping[str, Any], clave: str) -> dt.date | None:
    s = _texto(filtros, clave)
    if s is None:
        return None
    if not _FECHA.match(s):
        raise invalido(f'La fecha «{clave}» debe tener la forma AAAA-MM-DD.', clave)
    try:
        return dt.date.fromisoformat(s)
    except ValueError:
        raise invalido(f'La fecha «{clave}» no existe.', clave) from None


def rango(filtros: Mapping[str, Any]) -> tuple[dt.date | None, dt.date | None]:
    d, h = fecha(filtros, 'desde'), fecha(filtros, 'hasta')
    if d and h and d > h:
        raise invalido('«desde» no puede ser posterior a «hasta».', 'desde')
    return d, h


def entero(filtros: Mapping[str, Any], clave: str, omision: int, minimo: int, maximo: int) -> int:
    s = _texto(filtros, clave)
    if s is None:
        return omision
    if not re.fullmatch(r'\d{1,7}', s):
        raise invalido(f'«{clave}» debe ser un número entero.', clave)
    n = int(s)
    if not minimo <= n <= maximo:
        raise invalido(f'«{clave}» debe estar entre {minimo} y {maximo}.', clave)
    return n


def uno_de(filtros: Mapping[str, Any], clave: str, opciones: tuple[str, ...], omision: str | None) -> str | None:
    s = _texto(filtros, clave)
    if s is None:
        return omision
    if s not in opciones:
        raise invalido(f'Valor no válido para «{clave}».', clave)
    return s


def lista_de(filtros: Mapping[str, Any], clave: str, opciones: tuple[str, ...]) -> tuple[str, ...] | None:
    """csv validado contra `opciones` (sin repetidos, en el orden de `opciones`)."""
    s = _texto(filtros, clave)
    if s is None:
        return None
    partes = [p.strip() for p in s.split(',') if p.strip()]
    if not partes:
        return None
    malos = [p for p in partes if p not in opciones]
    if malos:
        raise invalido(f'Valor no válido para «{clave}».', clave)
    return tuple(o for o in opciones if o in partes)


def booleano(filtros: Mapping[str, Any], clave: str) -> bool | None:
    s = _texto(filtros, clave)
    if s is None:
        return None
    if s.lower() in ('1', 'true', 'si', 'sí'):
        return True
    if s.lower() in ('0', 'false', 'no'):
        return False
    raise invalido(f'«{clave}» debe ser 1 o 0.', clave)


def texto_libre(filtros: Mapping[str, Any], clave: str, maximo: int = 200) -> str | None:
    s = _texto(filtros, clave)
    if s is None:
        return None
    if len(s) > maximo or _CONTROL.search(s):
        raise invalido(f'«{clave}» no es válido.', clave)
    return s


def id_numerico(valor: Any, que: str) -> str:
    s = str(valor or '').strip()
    if not _ID_NUMERICO.match(s):
        raise invalido(f'El identificador de {que} no es válido.', que)
    return s


def id_muestra(valor: Any) -> str:
    s = str(valor or '').strip()
    if not _ID_MUESTRA.match(s):
        raise invalido('El identificador de la muestra no es válido.', 'application_id')
    return s


def clave_tienda(valor: Any) -> str:
    s = str(valor or '')
    if not s.strip() or len(s) > 200 or _CONTROL.search(s):
        raise invalido('La tienda no es válida.', 'tienda_key')
    return s


@dataclass(frozen=True)
class Periodo:
    clave: str
    desde: dt.date
    hasta: dt.date
    anterior_desde: dt.date | None
    anterior_hasta: dt.date | None
    granularidad: str


def periodo(clave: Any) -> str:
    """Valida `periodo` del tablero: 7d · 30d · 90d · 12m · todo · AAAA-MM (03 §5.1)."""
    s = str(clave or '').strip() or '30d'
    if s in ('7d', '30d', '90d', '12m', 'todo'):
        return s
    m = _PERIODO_MES.match(s)
    if m and 2000 <= int(m.group(1)) <= 2100 and 1 <= int(m.group(2)) <= 12:
        return s
    raise invalido('El periodo no es válido. Usa 7d, 30d, 90d, 12m, todo o AAAA-MM.', 'periodo')


def resolver_periodo(clave: str, hoy: dt.date, primera_fecha: dt.date | None) -> Periodo:
    """Fechas de un periodo validado (port de analitica_ref.Analitica.periodo)."""
    h = hoy
    if clave.endswith('d'):
        n = int(clave[:-1])
        d = h - dt.timedelta(days=n - 1)
        return Periodo(clave, d, h, d - dt.timedelta(days=n), d - dt.timedelta(days=1), 'dia' if n <= 31 else 'semana')
    if clave == '12m':
        d = dt.date(h.year - 1, h.month, 1) + dt.timedelta(days=31)
        return Periodo(clave, dt.date(d.year, d.month, 1), h, None, None, 'mes')
    if clave == 'todo':
        return Periodo(clave, min(primera_fecha, h) if primera_fecha else h, h, None, None, 'mes')
    y, m = map(int, clave.split('-'))
    d = dt.date(y, m, 1)
    fin = dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)
    ant_fin = d - dt.timedelta(days=1)
    return Periodo(clave, d, fin, dt.date(ant_fin.year, ant_fin.month, 1), ant_fin, 'dia')


# ---------------------------------------------------------------------- filtros por lectura
@dataclass(frozen=True)
class FiltrosMuestras:
    grupos: tuple[str, ...] | None
    clases: tuple[str, ...] | None
    tienda: str | None
    q: str | None
    orden: str
    recibidas: bool | None


def muestras(filtros: Mapping[str, Any] | None) -> FiltrosMuestras:
    f = solo_permitidos(filtros, ('grupo', 'clase', 'tienda', 'q', 'orden', 'recibidas'))
    return FiltrosMuestras(grupos=lista_de(f, 'grupo', reglas.GRUPOS), clases=lista_de(f, 'clase', reglas.CLASES),
                           tienda=texto_libre(f, 'tienda'), q=texto_libre(f, 'q', 100),
                           orden=uno_de(f, 'orden', reglas.ORDENES_MUESTRAS, 'prioridad') or 'prioridad',
                           recibidas=booleano(f, 'recibidas'))


def tiendas(filtros: Mapping[str, Any] | None) -> tuple[str, dt.date | None, dt.date | None]:
    f = solo_permitidos(filtros, ('orden', 'desde', 'hasta'))
    d, h = rango(f)
    return uno_de(f, 'orden', reglas.ORDENES_TIENDAS, 'atencion') or 'atencion', d, h


def solo_rango(filtros: Mapping[str, Any] | None) -> tuple[dt.date | None, dt.date | None]:
    return rango(solo_permitidos(filtros, ('desde', 'hasta')))


def serie(filtros: Mapping[str, Any] | None) -> tuple[str | None, dt.date | None, dt.date | None]:
    f = solo_permitidos(filtros, ('granularidad', 'desde', 'hasta'))
    d, h = rango(f)
    return uno_de(f, 'granularidad', reglas.GRANULARIDADES, None), d, h


def con_limite(filtros: Mapping[str, Any] | None) -> tuple[dt.date | None, dt.date | None, int]:
    f = solo_permitidos(filtros, ('desde', 'hasta', 'limite'))
    d, h = rango(f)
    return d, h, entero(f, 'limite', 50, 1, 1000)


ORDENES_CATALOGO: tuple[str, ...] = ('publicado', 'vistas', 'comision')
INCLUIR_CATALOGO: tuple[str, ...] = ('publicos', 'historial')


def catalogo(filtros: Mapping[str, Any] | None) -> tuple[str, bool, int]:
    """GET /api/catalogo/videos (rev. 6): orden, ¿incluir videos que solo quedan en el historial?, límite."""
    f = solo_permitidos(filtros, ('orden', 'incluir', 'limite'))
    orden = uno_de(f, 'orden', ORDENES_CATALOGO, 'publicado') or 'publicado'
    return orden, uno_de(f, 'incluir', INCLUIR_CATALOGO, 'publicos') == 'historial', entero(f, 'limite', 200, 1, 2000)


@dataclass(frozen=True)
class FiltrosOrdenes:
    desde: dt.date | None
    hasta: dt.date | None
    estados: tuple[str, ...] | None
    tienda: str | None
    producto: str | None
    video: str | None
    q: str | None
    pagina: int
    por_pagina: int


def ordenes(filtros: Mapping[str, Any] | None) -> FiltrosOrdenes:
    f = solo_permitidos(filtros, ('desde', 'hasta', 'estado', 'tienda', 'producto', 'video', 'q', 'pagina', 'por_pagina'))
    d, h = rango(f)
    producto, video = texto_libre(f, 'producto', 30), texto_libre(f, 'video', 30)
    if producto is not None:
        id_numerico(producto, 'producto')
    if video is not None:
        id_numerico(video, 'video')
    return FiltrosOrdenes(desde=d, hasta=h, estados=lista_de(f, 'estado', reglas.ESTADOS_ORDEN),
                          tienda=texto_libre(f, 'tienda'), producto=producto, video=video, q=texto_libre(f, 'q', 100),
                          pagina=entero(f, 'pagina', 1, 1, 1000000), por_pagina=entero(f, 'por_pagina', 50, 1, 200))
