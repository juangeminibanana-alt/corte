"""Utilidades puras del hub (BUILD_SPEC §3.2): montos, fechas en hora de México, textos, filtro de secretos y
canonicalización CH1. Portado de spec/verificacion/comun.py SIN rutas a research/ ni reglas de clasificación (esas
viven en creatorhub.clasificador, de hub-sync). Solo librería estándar.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import time
import urllib.parse
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Iterable

# México (zona centro) no tiene horario de verano desde oct-2022: desfase fijo UTC−6 (contrato.ts, 03 §3.1).
# Python en Windows no trae base de zonas (zoneinfo necesitaría tzdata), así que no se usa zoneinfo.
TZ_OFFSET_S = -6 * 3600
TZ_MX = dt.timezone(dt.timedelta(seconds=TZ_OFFSET_S), 'America/Mexico_City')


# --------------------------------------------------------------------------- montos
_NUM = re.compile(r'\d[\d,]*(?:\.\d+)?|\.\d+')
_SEP_RANGO = re.compile(r'(?<=[\d)])\s*[-–]\s*(?=[$(]?\s*\d|MX)')


def parse_monto(valor: Any) -> int | None:
    """Texto de la API -> centavos (int) o None.

    '$12.34' -> 1234 · '$1,234.50' -> 123450 · 'MX$ 10' -> 1000 · '-$3.00' -> -300 · '' / None -> None.
    Formato México: coma = miles, punto = decimales. Nunca float para sumar dinero (redondeo half-up con Decimal).
    """
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float, Decimal)):
        return int((Decimal(str(valor)) * 100).quantize(Decimal(1), ROUND_HALF_UP))
    s = str(valor).strip()
    if not s:
        return None
    negativo = s.startswith('-') or s.startswith('(') or '-$' in s
    m = _NUM.search(s)
    if not m:
        return None
    try:
        d = Decimal(m.group(0).replace(',', ''))
    except InvalidOperation:
        return None
    c = int((d * 100).quantize(Decimal(1), ROUND_HALF_UP))
    return -c if negativo else c


def parse_rango(valor: Any) -> tuple[int | None, int | None]:
    """'19.15 - 19.25' -> (1915, 1925) · '19.15-19.25' -> (1915, 1925) · '10.89' -> (1089, 1089) · '' -> (None, None).

    Solo se corta en un guion que va DESPUÉS de un dígito y ANTES de otro número: así '-$3.00' conserva su signo.
    """
    if valor is None or str(valor).strip() == '':
        return (None, None)
    partes = [p for p in _SEP_RANGO.split(str(valor).strip()) if p.strip()]
    nums = [n for n in (parse_monto(p) for p in partes) if n is not None]
    if not nums:
        return (None, None)
    return (min(nums), max(nums))


def fmt_mxn(centavos: int | None) -> str:
    """Centavos -> '$1,234.50' (para registros y pruebas; la interfaz formatea con @/dominio). None -> '—'."""
    if centavos is None:
        return '—'
    signo = '-' if centavos < 0 else ''
    entero, resto = divmod(abs(int(centavos)), 100)
    return f'{signo}${entero:,}.{resto:02d}'


def precio_venta_por_comision(comision_monto_min_centavos: int | None, comision_bp: int | None) -> int | None:
    """Precio de venta MÍNIMO implícito en commission.amount (= precio de venta × tasa), en centavos."""
    if not comision_monto_min_centavos or not comision_bp:
        return None
    return int((Decimal(comision_monto_min_centavos) * 10000 / Decimal(comision_bp)).quantize(Decimal(1), ROUND_HALF_UP))


# --------------------------------------------------------------------------- tiempo (UTC−6 fijo)
def ts_local(ts: int | float) -> dt.datetime:
    return dt.datetime.fromtimestamp(int(ts), TZ_MX)


def fecha_local(ts: int | float) -> str:
    """Epoch UTC -> 'YYYY-MM-DD' en hora de México."""
    return ts_local(ts).strftime('%Y-%m-%d')


def mes_local(ts: int | float) -> str:
    return ts_local(ts).strftime('%Y-%m')


def semana_local(ts: int | float) -> str:
    """Lunes (YYYY-MM-DD) de la semana ISO que contiene ts, en hora de México."""
    d = ts_local(ts).date()
    return (d - dt.timedelta(days=d.weekday())).isoformat()


def epoch_de_fecha_local(fecha_iso: str, hora: int = 12, segundos_extra: int = 0) -> int:
    """'YYYY-MM-DD' (hora de México) -> epoch UTC a la hora indicada."""
    y, m, d = map(int, fecha_iso.split('-'))
    return int(dt.datetime(y, m, d, hora, 0, 0, tzinfo=TZ_MX).timestamp()) + segundos_extra


def dias_calendario(desde_ts: int | float | None, hasta_ts: int | float) -> int | None:
    """Diferencia en días CALENDARIO locales (UTC−6) de `hasta_ts` a `desde_ts`: 0 = mismo día, 1 = mañana, −1 = ayer."""
    if not desde_ts:
        return None
    return (ts_local(desde_ts).date() - ts_local(hasta_ts).date()).days


# --------------------------------------------------------------------------- textos
def norm_tienda(nombre: str | None) -> str | None:
    """Clave estable de tienda: minúsculas, espacios colapsados (la API de productos no da shop_id).
    Devuelve None si el nombre queda vacío (nunca se crea una tienda fantasma con clave '')."""
    k = ' '.join((nombre or '').lower().split())
    return k or None


def norm_estado(s: Any) -> str | None:
    """Estados de la API normalizados al ingerirlos: sin espacios y en mayúsculas ('OPS_ COMPLETED' -> 'OPS_COMPLETED')."""
    if s is None:
        return None
    return re.sub(r'\s+', '', str(s)).upper() or None


_PROMO = re.compile(r'^\s*(?:BUEN FIN\s*)?(?:【[^】]{0,40}】\s*)+', re.IGNORECASE)


def limpiar_titulo(titulo: str | None) -> str | None:
    """Quita prefijos promocionales tipo '【Buen Fin】' para mostrar en la interfaz."""
    if not titulo:
        return titulo
    t = _PROMO.sub('', titulo).strip()
    return t or titulo.strip()


def huella(*campos: Any) -> str:
    """SHA-1 estable de los campos (detección de cambios en la sincronización; no es un uso criptográfico)."""
    return hashlib.sha1(json.dumps(campos, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


# --------------------------------------------------------------------------- filtro de secretos (03 §7.6)
_SECRETO_QUERY = re.compile(
    r"(?<![A-Za-z0-9_])(app_secret|access_token|refresh_token|auth_code|code|sign|state|pair_secret|device_key|s|t)"
    r"=[^&\s\"',}]+", re.IGNORECASE)
_SECRETO_JSON = re.compile(
    r"([\"'])(app_secret|access_token|refresh_token|auth_code|code|sign|state|pair_secret|device_key)\1\s*:\s*"
    r"([\"'])[^\"']*\3", re.IGNORECASE)
_SECRETO_CABECERA = re.compile(r'(x-tts-access-token|authorization)\s*[:=]\s*\S+', re.IGNORECASE)
_SECRETO_TTP = re.compile(r'TTP_[A-Za-z0-9_\-]+')


def limpiar(texto: Any, secretos_vivos: Iterable[str] = ()) -> Any:
    """Reemplaza secretos por *** en un texto FINAL (mensaje + args + traceback). Se aplica en el Formatter de logging,
    al construir ErrorApi y al serializar ErrorRespuesta. `secretos_vivos`: valores literales de la bóveda y de las
    claves de dispositivos (solo los de 8 caracteres o más). Los códigos numéricos (105001) se conservan."""
    if not texto:
        return texto
    s = str(texto)
    for v in sorted((x for x in secretos_vivos if x and len(x) >= 8), key=len, reverse=True):
        s = s.replace(v, '***')
    s = _SECRETO_TTP.sub('***', s)
    s = _SECRETO_JSON.sub(lambda m: f'{m.group(1)}{m.group(2)}{m.group(1)}: {m.group(3)}***{m.group(3)}', s)
    s = _SECRETO_QUERY.sub(lambda m: f'{m.group(1)}=***', s)
    s = _SECRETO_CABECERA.sub(lambda m: f'{m.group(1)}: ***', s)
    return s


# --------------------------------------------------------------------------- canonicalización CH1 (03 §6.6)
_NO_RESERVADOS = frozenset(b'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~')


def pct(texto: str) -> str:
    """Percent-encoding RFC 3986: solo A-Z a-z 0-9 - . _ ~ sin escapar; %XX en MAYÚSCULAS; espacio = %20; UTF-8."""
    return ''.join(chr(b) if b in _NO_RESERVADOS else '%%%02X' % b for b in texto.encode('utf-8'))


def canonico_ruta_query(ruta_query: str) -> str:
    """Forma canónica de ruta + query para CH1, idéntica en Python y en Java (vectores_ch1.json).
    Ruta: cada segmento se decodifica (%XX) y se vuelve a codificar con pct(). Query: pares decodificados como
    application/x-www-form-urlencoded ('+' = espacio), recodificados con pct(), ordenados por (clave, valor) y unidos."""
    u = urllib.parse.urlsplit(ruta_query)
    ruta = '/'.join(pct(urllib.parse.unquote(seg)) for seg in u.path.split('/'))
    pares = sorted((pct(k), pct(v)) for k, v in urllib.parse.parse_qsl(u.query, keep_blank_values=True))
    q = '&'.join(f'{k}={v}' for k, v in pares)
    return ruta + ('?' + q if q else '')


# --------------------------------------------------------------------------- archivos
def escribir_atomico(ruta: str, datos: bytes, intentos: int = 10) -> None:
    """Escritura atómica: `<ruta>.nuevo` + flush + fsync + os.replace, con reintentos (Windows devuelve
    PermissionError si otro proceso, p. ej. un antivirus, tiene abierto el destino un instante)."""
    nuevo = ruta + '.nuevo'
    try:
        with open(nuevo, 'wb') as f:
            f.write(datos)
            f.flush()
            os.fsync(f.fileno())
        for i in range(intentos):
            try:
                os.replace(nuevo, ruta)
                return
            except PermissionError:
                if i == intentos - 1:
                    raise
                time.sleep(0.05 * (i + 1))
    except BaseException:
        try:                                    # si no se pudo reemplazar, no dejar `<ruta>.nuevo` tirado
            os.remove(nuevo)
        except OSError:
            pass
        raise
