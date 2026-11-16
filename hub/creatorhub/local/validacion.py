"""Validación de los cuerpos del estado local (spec/contrato.ts: PlanVideoCrear/Cambios, AvisoCrear/Cambios, NotaCrear/
Cambios, RecordatorioCrear/Cambios, plantillas y PreferenciasSincronizadas) y de los filtros de listado.

Un campo con tipo o valor fuera de lo permitido da ErrorDominio('parametros_invalidos', …, http=422); un parámetro de
listado desconocido, http=400. Los campos de solo lectura de un objeto versionado (creado_at, actualizado_at, rev en
una creación, dispositivo_id, en_cohorte_desde_at) se ignoran si vienen; cualquier otra clave desconocida es un error.
"""
from __future__ import annotations

import datetime as dt
import re
import urllib.parse
from typing import Any, Callable, Mapping

from ..errores import ErrorDominio
from .serial import PREFERENCIAS_POR_OMISION

_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$')
_DIGITOS = re.compile(r'^\d{1,25}$')
_FECHA = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_HORA = re.compile(r'^([01]\d|2[0-3]):[0-5]\d$')
_CONTROL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')       # se permiten \t \n \r (textos de mensajes)
_VIDEO_EN_ENLACE = re.compile(r'/video/(\d{1,25})(?:[/?#]|$)')

ETAPAS = ('por_planear', 'planeada', 'video_listo', 'programada', 'publicada', 'no_se_puede')
VINCULOS = ('manual', 'sugerido_por_ventas', 'confirmado_por_tiktok', 'video_previo', 'video_previo_aceptado')
MOTIVOS = ('agotado', 'desactivado', 'no_llego', 'incompleta', 'no_va_con_mi_contenido', 'otro')
ORIGENES_AVISO = ('copiado', 'por_mi_cuenta')
ENTIDADES_NOTA = ('muestra', 'tienda', 'producto', 'video', 'orden', 'general')
ENTIDADES_RECORDATORIO = ('muestra', 'tienda', 'plan', 'general')
REPETIR = ('no', 'diario', 'semanal')
ESTADOS_RECORDATORIO = ('activo', 'hecho', 'cancelado')
SOLO_LECTURA = ('creado_at', 'actualizado_at', 'dispositivo_id', 'en_cohorte_desde_at')
EPOCH_MAX = 2 ** 41


def invalido(campo: str, mensaje: str | None = None, http: int = 422) -> ErrorDominio:
    return ErrorDominio('parametros_invalidos', mensaje or f'El campo «{campo}» no es válido.', http=http,
                        detalle={'campo': campo})


# ---------------------------------------------------------------------- validadores de un valor
def ident(v: Any, campo: str = 'id') -> str:
    if not isinstance(v, str) or not _ID.match(v):
        raise invalido(campo)
    return v


def texto(v: Any, campo: str, minimo: int = 0, maximo: int = 5000, nulo: bool = False) -> str | None:
    if v is None and nulo:
        return None
    if not isinstance(v, str) or _CONTROL.search(v) or not minimo <= len(v) <= maximo:
        raise invalido(campo)
    if minimo and not v.strip():
        raise invalido(campo)
    return v


def fecha(v: Any, campo: str, nulo: bool = True) -> str | None:
    if v is None and nulo:
        return None
    if not isinstance(v, str) or not _FECHA.match(v):
        raise invalido(campo)
    try:
        dt.date.fromisoformat(v)
    except ValueError:
        raise invalido(campo) from None
    return v


def epoch(v: Any, campo: str, nulo: bool = True) -> int | None:
    if v is None and nulo:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v < EPOCH_MAX:
        raise invalido(campo)
    return v


def entero(v: Any, campo: str, minimo: int, maximo: int) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or not minimo <= v <= maximo:
        raise invalido(campo)
    return v


def booleano(v: Any, campo: str) -> bool:
    if not isinstance(v, bool):
        raise invalido(campo)
    return v


def opcion(v: Any, campo: str, opciones: tuple[str, ...], nulo: bool = False) -> str | None:
    if v is None and nulo:
        return None
    if v not in opciones:
        raise invalido(campo)
    return v


def digitos(v: Any, campo: str, nulo: bool = True) -> str | None:
    if v is None and nulo:
        return None
    if not isinstance(v, str) or not _DIGITOS.match(v):
        raise invalido(campo)
    return v


def lista_digitos(v: Any, campo: str, maximo: int = 200) -> list[str]:
    if not isinstance(v, list) or len(v) > maximo:
        raise invalido(campo)
    return list(dict.fromkeys(digitos(x, campo, nulo=False) for x in v))  # type: ignore[misc]


def lista_ids(v: Any, campo: str, maximo: int = 200) -> list[str]:
    if not isinstance(v, list) or len(v) > maximo:
        raise invalido(campo)
    return list(dict.fromkeys(ident(x, campo) for x in v))


def enlace(v: Any, campo: str = 'enlace_video') -> str | None:
    if v is None:
        return None
    if not isinstance(v, str) or len(v) > 500 or _CONTROL.search(v):
        raise invalido(campo)
    u = urllib.parse.urlsplit(v.strip())
    if u.scheme not in ('https', 'http') or not u.hostname:
        raise invalido(campo, 'El enlace del video debe empezar con https://')
    return v.strip()


def content_id_de_enlace(url: str | None) -> str | None:
    """content_id de un enlace completo 'https://www.tiktok.com/@usuario/video/<dígitos>' (01 §7.2); None si es corto."""
    if not url:
        return None
    u = urllib.parse.urlsplit(url)
    if not (u.hostname or '').endswith('tiktok.com'):
        return None
    m = _VIDEO_EN_ENLACE.search(u.path + ('?' if u.query else ''))
    return m.group(1) if m else None


def compromisos(v: Any, campo: str = 'compromisos') -> dict[str, str]:
    if not isinstance(v, dict) or len(v) > 200:
        raise invalido(campo)
    return {ident(k, campo): fecha(f, campo, nulo=False) for k, f in v.items()}  # type: ignore[misc]


def rev(cambios: Mapping[str, Any]) -> int:
    v = cambios.get('rev')
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        raise invalido('rev', 'Falta la versión (rev) del cambio.')
    return v


def _dict(datos: Any, que: str = 'cuerpo') -> dict[str, Any]:
    if not isinstance(datos, Mapping):
        raise invalido(que, 'El cuerpo debe ser un objeto JSON.')
    return dict(datos)


def _campos(datos: Mapping[str, Any], validadores: Mapping[str, Callable[[Any], Any]],
            obligatorios: tuple[str, ...] = (), ignorar: tuple[str, ...] = SOLO_LECTURA) -> dict[str, Any]:
    sobran = [k for k in datos if k not in validadores and k not in ignorar]
    if sobran:
        raise invalido(sorted(sobran)[0], f'Campo no permitido: «{sorted(sobran)[0]}».')
    faltan = [k for k in obligatorios if k not in datos]
    if faltan:
        raise invalido(faltan[0], f'Falta el campo «{faltan[0]}».')
    return {k: validadores[k](v) for k, v in datos.items() if k in validadores}


# ---------------------------------------------------------------------- PlanVideo
_PLAN: dict[str, Callable[[Any], Any]] = {
    'application_id': lambda v: None if v is None else ident(v, 'application_id'),
    'product_id': lambda v: digitos(v, 'product_id'),
    'tienda_key': lambda v: texto(v, 'tienda_key', 1, 200, nulo=True),
    'titulo': lambda v: texto(v, 'titulo', 1, 200),
    'fecha_plan': lambda v: fecha(v, 'fecha_plan'),
    'estado': lambda v: opcion(v, 'estado', ETAPAS),
    'fecha_video_listo': lambda v: fecha(v, 'fecha_video_listo'),
    'programada_para_at': lambda v: epoch(v, 'programada_para_at'),
    'fecha_publicada': lambda v: fecha(v, 'fecha_publicada'),
    'content_id': lambda v: digitos(v, 'content_id'),
    'enlace_video': lambda v: enlace(v),
    'vinculo_origen': lambda v: opcion(v, 'vinculo_origen', VINCULOS, nulo=True),
    'sugerencias_descartadas': lambda v: lista_digitos(v, 'sugerencias_descartadas'),
    'motivo_no_se_puede': lambda v: opcion(v, 'motivo_no_se_puede', MOTIVOS, nulo=True),
    'motivo_texto': lambda v: texto(v, 'motivo_texto', 0, 300, nulo=True),
    'fijada': lambda v: booleano(v, 'fijada'),
    'nombre_corto': lambda v: texto(v, 'nombre_corto', 0, 60, nulo=True),
    'notas': lambda v: texto(v, 'notas', 0, 5000, nulo=True),
    'orden': lambda v: entero(v, 'orden', -10 ** 9, 10 ** 9),
}


def plan_crear(datos: Any) -> dict[str, Any]:
    d = _dict(datos)
    valores = _campos(d, {'id': ident, **_PLAN}, obligatorios=('id', 'titulo'), ignorar=SOLO_LECTURA + ('rev',))
    return valores


def plan_cambios(cambios: Any) -> tuple[int, dict[str, Any]]:
    d = _dict(cambios)
    r = rev(d)
    return r, _campos({k: v for k, v in d.items() if k != 'rev'}, _PLAN)


def coherencia_plan(p: Mapping[str, Any]) -> None:
    """Datos obligatorios por etapa (01 §2.4) y la regla del video previo (03 §6.2): 422 si no se cumplen."""
    e = p.get('estado')
    if e == 'planeada' and not p.get('fecha_plan'):
        raise invalido('fecha_plan', 'Para planear, elige qué día haces este video.')
    if e == 'programada' and p.get('programada_para_at') is None:
        raise invalido('programada_para_at', 'Para marcarla como programada, indica la fecha y la hora.')
    if e == 'no_se_puede' and not p.get('motivo_no_se_puede'):
        raise invalido('motivo_no_se_puede', 'Elige por qué no puedes hacer este video.')
    if e == 'publicada' and p.get('vinculo_origen') == 'video_previo':
        raise invalido('vinculo_origen', 'Un video anterior a la muestra no cuenta como publicado. Si la tienda lo '
                                         'aceptó, márcalo como «La tienda aceptó este video».')


# ---------------------------------------------------------------------- AvisoTienda
_AVISO_CREAR: dict[str, Callable[[Any], Any]] = {
    'id': ident,
    'tienda_key': lambda v: texto(v, 'tienda_key', 1, 200),
    'solicitud_ids': lambda v: lista_ids(v, 'solicitud_ids'),
    'plantilla_id': lambda v: ident(v, 'plantilla_id'),
    'texto': lambda v: texto(v, 'texto', 0, 5000),
    'compromisos': compromisos,
    'origen': lambda v: opcion(v, 'origen', ORIGENES_AVISO),
    'fecha_anterior': lambda v: fecha(v, 'fecha_anterior'),
    'copiado_at': lambda v: epoch(v, 'copiado_at'),
    'marcado_enviado_at': lambda v: epoch(v, 'marcado_enviado_at'),
}
_AVISO_CAMBIOS: dict[str, Callable[[Any], Any]] = {
    'texto': lambda v: texto(v, 'texto', 0, 5000),
    'compromisos': compromisos,
    'marcado_enviado_at': lambda v: epoch(v, 'marcado_enviado_at'),
    'quitado_at': lambda v: epoch(v, 'quitado_at'),
}


def aviso_crear(datos: Any) -> dict[str, Any]:
    return _campos(_dict(datos), _AVISO_CREAR,
                   obligatorios=('id', 'tienda_key', 'solicitud_ids', 'plantilla_id', 'texto', 'compromisos', 'origen'),
                   ignorar=SOLO_LECTURA + ('rev', 'quitado_at'))


def aviso_cambios(cambios: Any) -> tuple[int, dict[str, Any]]:
    d = _dict(cambios)
    return rev(d), _campos({k: v for k, v in d.items() if k != 'rev'}, _AVISO_CAMBIOS)


# ---------------------------------------------------------------------- Nota y Recordatorio
_NOTA: dict[str, Callable[[Any], Any]] = {
    'id': ident,
    'entidad': lambda v: opcion(v, 'entidad', ENTIDADES_NOTA),
    'entidad_id': lambda v: texto(v, 'entidad_id', 1, 200, nulo=True),
    'texto': lambda v: texto(v, 'texto', 1, 5000),
    'fijada': lambda v: booleano(v, 'fijada'),
}


def nota_crear(datos: Any) -> dict[str, Any]:
    return _campos(_dict(datos), _NOTA, obligatorios=('id', 'entidad', 'entidad_id', 'texto'),
                   ignorar=SOLO_LECTURA + ('rev',))


def nota_cambios(cambios: Any) -> tuple[int, dict[str, Any]]:
    d = _dict(cambios)
    return rev(d), _campos({k: v for k, v in d.items() if k != 'rev'},
                           {'texto': _NOTA['texto'], 'fijada': _NOTA['fijada']})


_RECORDATORIO: dict[str, Callable[[Any], Any]] = {
    'id': ident,
    'titulo': lambda v: texto(v, 'titulo', 1, 200),
    'vence_at': lambda v: epoch(v, 'vence_at', nulo=False),
    'entidad': lambda v: opcion(v, 'entidad', ENTIDADES_RECORDATORIO),
    'entidad_id': lambda v: texto(v, 'entidad_id', 1, 200, nulo=True),
    'repetir': lambda v: opcion(v, 'repetir', REPETIR),
}
_RECORDATORIO_CAMBIOS: dict[str, Callable[[Any], Any]] = {
    'titulo': _RECORDATORIO['titulo'], 'vence_at': _RECORDATORIO['vence_at'], 'repetir': _RECORDATORIO['repetir'],
    'estado': lambda v: opcion(v, 'estado', ESTADOS_RECORDATORIO),
    'pospuesto_hasta': lambda v: epoch(v, 'pospuesto_hasta'),
}


def recordatorio_crear(datos: Any) -> dict[str, Any]:
    return _campos(_dict(datos), _RECORDATORIO, obligatorios=('id', 'titulo', 'vence_at'),
                   ignorar=SOLO_LECTURA + ('rev', 'estado', 'pospuesto_hasta', 'notificado_at'))


def recordatorio_cambios(cambios: Any) -> tuple[int, dict[str, Any]]:
    d = _dict(cambios)
    return rev(d), _campos({k: v for k, v in d.items() if k != 'rev'}, _RECORDATORIO_CAMBIOS)


# ---------------------------------------------------------------------- plantillas y preferencias
def plantilla_cambios(cambios: Any) -> tuple[int, dict[str, Any]]:
    d = _dict(cambios)
    return rev(d), _campos({k: v for k, v in d.items() if k != 'rev'},
                           {'nombre': lambda v: texto(v, 'nombre', 1, 60), 'cuerpo': lambda v: texto(v, 'cuerpo', 1, 5000)},
                           ignorar=('id', 'predeterminada') + SOLO_LECTURA)


def _hora(v: Any) -> str:
    if not isinstance(v, str) or not _HORA.match(v):
        raise invalido('hora_recordatorio')
    return v


def _dias(v: Any) -> list[int]:
    if not isinstance(v, list) or not 1 <= len(v) <= 7:
        raise invalido('dias_videos')
    dias = [entero(x, 'dias_videos', 0, 6) for x in v]
    if len(set(dias)) != len(dias):
        raise invalido('dias_videos')
    return sorted(dias)


_PREFERENCIAS: dict[str, Callable[[Any], Any]] = {
    'capacidad_videos_dia': lambda v: entero(v, 'capacidad_videos_dia', 1, 10),
    'dias_videos': _dias,
    'programo_mis_videos': lambda v: booleano(v, 'programo_mis_videos'),
    'firma': lambda v: texto(v, 'firma', 0, 200),
    'recordatorio_diario': lambda v: booleano(v, 'recordatorio_diario'),
    'hora_recordatorio': lambda v: _hora(v),
    'aviso_por_vencer': lambda v: booleano(v, 'aviso_por_vencer'),
    'aviso_promesas': lambda v: booleano(v, 'aviso_promesas'),
    'aviso_atrasados': lambda v: booleano(v, 'aviso_atrasados'),
    'resumen_semanal': lambda v: booleano(v, 'resumen_semanal'),
    'orden_plan': lambda v: opcion(v, 'orden_plan', ('sugerido', 'por_tipo_de_prenda')),
    'umbral_publicado_sin_ventas_dias': lambda v: entero(v, 'umbral_publicado_sin_ventas_dias', 1, 365),
    'tema': lambda v: opcion(v, 'tema', ('sistema', 'claro', 'oscuro')),
    'reducir_animaciones': lambda v: opcion(v, 'reducir_animaciones', ('sistema', 'si', 'no')),
}
if set(_PREFERENCIAS) != set(PREFERENCIAS_POR_OMISION):          # las dos listas deben moverse juntas
    raise RuntimeError('validacion._PREFERENCIAS no coincide con serial.PREFERENCIAS_POR_OMISION')


def preferencias_cambios(cambios: Any) -> tuple[int, dict[str, Any]]:
    d = _dict(cambios)
    return rev(d), _campos({k: v for k, v in d.items() if k != 'rev'}, _PREFERENCIAS)


# ---------------------------------------------------------------------- filtros de listado (query cruda)
def filtros(filtros_: Mapping[str, Any] | None, permitidos: tuple[str, ...]) -> dict[str, str]:
    f = dict(filtros_ or {})
    sobran = sorted(k for k in f if k not in permitidos)
    if sobran:
        raise invalido(sobran[0], f'Parámetro no válido: «{sobran[0]}».', http=400)
    out: dict[str, str] = {}
    for k, v in f.items():
        if isinstance(v, (list, tuple)):
            if len(v) != 1:
                raise invalido(k, f'El parámetro «{k}» viene repetido.', http=400)
            v = v[0]
        s = str(v).strip() if v is not None else ''
        if s:
            if len(s) > 200 or _CONTROL.search(s):
                raise invalido(k, http=400)
            out[k] = s
    return out


def filtro_fecha(f: Mapping[str, str], clave: str) -> str | None:
    if clave not in f:
        return None
    try:
        return fecha(f[clave], clave, nulo=False)
    except ErrorDominio:
        raise invalido(clave, f'La fecha «{clave}» debe tener la forma AAAA-MM-DD.', http=400) from None


def filtro_opcion(f: Mapping[str, str], clave: str, opciones: tuple[str, ...]) -> str | None:
    if clave not in f:
        return None
    if f[clave] not in opciones:
        raise invalido(clave, f'Valor no válido para «{clave}».', http=400)
    return f[clave]
