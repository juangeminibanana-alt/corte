"""`CreatorHub.exe --autoprueba` (04 §A.2, §D.2 paso 6; BUILD_SPEC C3, §11.2).

Otra carpeta de datos (`%TEMP%\\CreatorHub-autoprueba`, vaciada al empezar: base NUEVA), otro mutex
(`Local\\CreatorHub.Autoprueba`), puerto 0, sin ventana ni LAN. Arranca el hub REAL en modo 'autoprueba' y comprueba:

  salud ............ GET /api/health → ok, versión = version.json
  base_nueva ....... la base no existía; ahora tiene todas las tablas de schema.sql, 11 plantillas sembradas y la fila de
                     preferencias, y ninguna muestra
  sin_activar_http . POST /local/activar NO existe (C40: la activación es solo el evento); un GET responde 4xx o lo
                     mismo que una ruta inventada (respaldo de SPA de los estáticos), nada propio
  pil_perezoso ..... PIL no está cargado en «listo» (C3)
  qr ............... PNG del QR con qrcode + pypng (lan/qr.py, sin PIL)
  pil .............. Pillow se importa APARTE, después de «listo» (`t_pil_ms`), y codifica un WebP
  edgechromium ..... `import webview.platforms.edgechromium` (CLR de .NET + WebView2 Core) → `t_edgechromium_ms`
  dpapi ............ CryptProtectData/CryptUnprotectData ida y vuelta
  cng .............. AES-256-GCM con bcrypt.dll ida y vuelta (y una etiqueta alterada se rechaza)
  identidad_tls .... ECDSA P-256 con CNG + llave PKCS#8 cifrada + DPAPI + `ssl.SSLContext.load_cert_chain` →
                     `t_identidad_tls_ms`

Escribe `<carpeta>\\autoprueba.json` y sale con 0 solo si todo pasó. Tiempos: `t_main_ms`, `t_import_ms` y
`t_hub_listo_ms` (y `t_total_ms`) son MARCAS desde que Windows creó el proceso (`ms_desde_inicio_proceso()`, incluye el
cargador de PyInstaller); `t_pil_ms`, `t_edgechromium_ms` y `t_identidad_tls_ms` son DURACIONES de esa sola operación.
`t_hub_listo_ms` se toma en cuanto el servidor escucha, antes de importar pywebview/edgechromium y PIL.

El código de salida NO depende del tope de 800 ms: la 1.ª corrida del build (04 §D.2 paso 6) es lenta a propósito (calienta
el análisis de Defender) y tiene que salir con 0; el build compara `t_hub_listo_ms` con el tope en la 2.ª. Para leer los
tiempos en una PC cargada, el informe agrega (todo medido sin sumar a `t_hub_listo_ms`):
  dentro_del_tope ............ t_hub_listo_ms ≤ 800
  marcas_ms .................. más marcas desde la creación del proceso, para repartir t_hub_listo_ms: `correr` (ya
                               importado este módulo, con config.py) · `previo_import_hub` (después del mutex y de
                               apartar la carpeta: lo propio del shell) · `previo_iniciar_hub` (cadena de creatorhub.hub
                               importada y registro listo). De ahí a t_hub_listo_ms es `iniciar_hub` (hub-api)
  t_hub_listo_cpu_ms ......... CPU (usuario + núcleo) que gastó el proceso hasta «listo»; `cpu_ms` lo desglosa
  cpu_sistema_pct ............ % de ocupación de la CPU de TODA la PC entre main() y «listo» (GetSystemTimes)
  referencia_cpu_listo_ms/referencia_cpu_ms/referencia_cpu_hilo_ms .. un bucle fijo justo después de «listo» y al final
                               (reloj y CPU del hilo): 30–60 ms en una PC sin carga. La que cuenta es la de «listo»: la
                               del final compite con los hilos del hub que ya corren (imágenes, planificador, CLR)
  piso_interprete_ms ......... solo desde el código: lo que tarda en abrir y cerrar un `python -I -S -c pass` (3 veces),
                               medido al final; es el piso del momento, por debajo del cual no puede bajar ningún arranque
  memoria, modulos_en_listo .. memoria libre de la PC y cuántos módulos había cargados en «listo»
  diagnostico ................ si quedó fuera del tope: si la PC estaba saturada (y por qué) o si hay que revisar imports
Al terminar escribe un resumen de una línea en stderr (si hay consola) y en el registro.
Sin `assert` (el exe se compila con optimize=1) ni unittest (excluido del exe). Lo que no hace falta antes de «listo»
(http.client, sqlite3, shutil, subprocess…) se importa dentro de cada comprobación. Antes de «listo» el shell no agrega
más módulos que los suyos (`__main__`, `instancia`, `autoprueba`) y `ctypes.wintypes`: todo lo demás ya lo importa la cadena
de `creatorhub.hub` (test_shell_autoprueba lo comprueba). Ojo: en modo 'autoprueba' el hub arma el transporte de demo
sintético (BUILD §6.3.1 paso 5), que genera los datos de muestra ANTES de «listo» (el arranque real no hace eso), y
`crear_servicio_lan` importa lan.servicio y compañía aunque vaya con sin_lan: las dos cosas son de `iniciar_hub` (desde
`marcas_ms.previo_iniciar_hub`), no del shell.
"""
from __future__ import annotations

import ctypes
import json
import logging
import os
import re
import sys
import tempfile
import time
from ctypes import wintypes
from typing import Any, Callable

from creatorhub import config
from creatorhub.plataforma.windows.instancia import ms_desde_inicio_proceso

_log = logging.getLogger('creatorhub.plataforma.autoprueba')

CARPETA = os.path.join(tempfile.gettempdir(), 'CreatorHub-autoprueba')
MUTEX = 'Local\\CreatorHub.Autoprueba'
MARCA = '.creatorhub-autoprueba'
INFORME = 'autoprueba.json'
TOPE_HUB_LISTO_MS = 800
ESPERA_MUTEX_MS = 60_000
PLANTILLAS_ESPERADAS = 11
ENTROPIA_PRUEBA = b'CreatorHub/autoprueba/v1'
TEXTO_QR = 'creatorhub://pair?v=1&h=' + '0' * 32
# rev. 4: el nombre puede ir entre comillas ('CREATE TABLE IF NOT EXISTS "imagenes"', como la deja RENAME TO)
_RE_TABLA = re.compile(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"?([A-Za-z_][A-Za-z0-9_]*)"?', re.IGNORECASE)


class FalloAutoprueba(Exception):
    pass


def exigir(condicion: Any, mensaje: str) -> None:
    if not condicion:
        raise FalloAutoprueba(mensaje)


# ---------------------------------------------------------------------- mutex propio (no choca con la app real)
class _MutexAutoprueba:
    def __init__(self, nombre: str = MUTEX) -> None:
        self.k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        self.k32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self.k32.CreateMutexW.restype = wintypes.HANDLE
        self.k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.k32.WaitForSingleObject.restype = wintypes.DWORD
        self.k32.ReleaseMutex.argtypes = self.k32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.nombre = nombre
        self.h: Any = None

    def tomar(self, espera_ms: int = ESPERA_MUTEX_MS) -> bool:
        self.h = self.k32.CreateMutexW(None, False, self.nombre)
        if not self.h:
            raise ctypes.WinError(ctypes.get_last_error())
        r = self.k32.WaitForSingleObject(self.h, espera_ms)
        return r in (0x0, 0x80)                                         # WAIT_OBJECT_0 / WAIT_ABANDONED

    def soltar(self) -> None:
        if self.h:
            self.k32.ReleaseMutex(self.h)
            self.k32.CloseHandle(self.h)
            self.h = None


# ---------------------------------------------------------------------- carpeta de datos
class CarpetaAjena(FalloAutoprueba):
    pass


def _vaciar(carpeta: str) -> None:
    import shutil
    for nombre in os.listdir(carpeta):
        ruta = os.path.join(carpeta, nombre)
        if os.path.isdir(ruta) and not os.path.islink(ruta):
            shutil.rmtree(ruta)
        else:
            os.remove(ruta)


def preparar_carpeta(carpeta: str, es_la_de_omision: bool) -> str | None:
    """Deja la carpeta vacía para que el hub cree una base NUEVA. Solo toca la carpeta de omisión o una que lleve la
    marca de una autoprueba anterior (o que esté vacía): nunca una carpeta de datos ajena pasada con --datos.
    Lo anterior se APARTA con un solo rename (barato, antes de «listo») y se borra al final: devuelve esa ruta."""
    carpeta = os.path.abspath(carpeta)
    apartada: str | None = None
    if os.path.isdir(carpeta):
        contenido = os.listdir(carpeta)
        if contenido and not es_la_de_omision and MARCA not in contenido:
            raise CarpetaAjena('La carpeta de --datos no es de una autoprueba (falta la marca); no se toca.')
        if contenido:
            apartada = f'{carpeta}.anterior-{os.getpid()}'
            try:
                os.rename(carpeta, apartada)
            except OSError:                                          # algo la tiene abierta: se vacía en su lugar
                apartada = None
                _vaciar(carpeta)
    os.makedirs(carpeta, exist_ok=True)
    with open(os.path.join(carpeta, MARCA), 'w', encoding='utf-8') as f:
        f.write('Carpeta temporal de la autoprueba de Corte. Se vacía en cada corrida.\n')
    return apartada


def borrar_apartadas(carpeta: str) -> None:
    """Borra lo que se apartó en esta corrida y lo que hayan dejado corridas interrumpidas."""
    import shutil
    padre, nombre = os.path.split(os.path.abspath(carpeta))
    try:
        hermanas = [n for n in os.listdir(padre) if n.startswith(nombre + '.anterior-')]
    except OSError:
        return
    for n in hermanas:
        shutil.rmtree(os.path.join(padre, n), ignore_errors=True)


def tablas_de_schema() -> set[str]:
    from importlib import resources
    texto = (resources.files('creatorhub') / 'almacen' / 'schema.sql').read_text(encoding='utf-8')
    return {m.group(1) for m in _RE_TABLA.finditer(texto)}


# ---------------------------------------------------------------------- comprobaciones
def _peticion_completa(puerto: int, metodo: str, ruta: str,
                       cabeceras: dict[str, str] | None = None) -> tuple[int, str, bytes]:
    """→ (status, Content-Type, cuerpo)."""
    import http.client
    con = http.client.HTTPConnection('127.0.0.1', puerto, timeout=10)
    try:
        con.request(metodo, ruta, body=b'' if metodo == 'POST' else None,
                    headers={'Host': f'127.0.0.1:{puerto}', **(cabeceras or {})})
        r = con.getresponse()
        return r.status, r.getheader('Content-Type') or '', r.read()
    finally:
        con.close()


def _peticion(puerto: int, metodo: str, ruta: str, cabeceras: dict[str, str] | None = None) -> tuple[int, bytes]:
    status, _, cuerpo = _peticion_completa(puerto, metodo, ruta, cabeceras)
    return status, cuerpo


def comprobar_salud(puerto: int) -> dict[str, Any]:
    status, cuerpo = _peticion(puerto, 'GET', '/api/health')
    exigir(status == 200, f'/api/health respondió {status}')
    datos = json.loads(cuerpo.decode('utf-8'))
    exigir(datos.get('ok') is True and datos.get('db_ok') is True, '/api/health sin ok/db_ok')
    exigir(datos.get('version') == config.VERSION, '/api/health con otra versión')
    return {'status': status, 'version': datos.get('version'), 'modo': datos.get('modo')}


RUTA_INEXISTENTE = '/autoprueba-ruta-que-no-existe'


def comprobar_sin_activar_http(puerto: int) -> dict[str, Any]:
    """C40: POST /local/activar no existe. Un GET a esa ruta puede caer en el respaldo de SPA de los estáticos
    (index.html, o la página «sin interfaz» si no hay dist), como cualquier ruta inventada. Vale un 4xx o una respuesta
    EXACTAMENTE igual a la de `RUTA_INEXISTENTE`; cualquier otra cosa indicaría que hay algo propio detrás."""
    status, _ = _peticion(puerto, 'POST', '/local/activar', {'X-CH-Hub': '1', 'Content-Length': '0'})
    exigir(not 200 <= status < 300, 'POST /local/activar respondió 2xx: no debe existir (C40)')
    get = _peticion_completa(puerto, 'GET', '/local/activar')
    igual = get == _peticion_completa(puerto, 'GET', RUTA_INEXISTENTE)
    exigir(get[0] >= 400 or igual, f'GET /local/activar respondió {get[0]} y distinto que una ruta inexistente: '
                                   'parece tener una ruta propia (C40)')
    return {'status': status, 'get_status': get[0], 'get_tipo': get[1].split(';')[0],
            'get_igual_que_ruta_inexistente': igual}


def comprobar_base_nueva(ruta_db: str, existia_antes: bool) -> dict[str, Any]:
    import sqlite3
    exigir(not existia_antes, 'la base ya existía antes de arrancar (no es nueva)')
    exigir(os.path.isfile(ruta_db), 'el hub no creó la base')
    con = sqlite3.connect(f'file:{ruta_db}?mode=ro', uri=True, timeout=5)
    try:
        tablas = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        esperadas = tablas_de_schema()
        faltan = sorted(esperadas - tablas)
        exigir(esperadas and not faltan, f'faltan tablas de schema.sql: {faltan}')
        plantillas = con.execute('SELECT COUNT(*) FROM plantillas').fetchone()[0]
        exigir(plantillas == PLANTILLAS_ESPERADAS, f'{plantillas} plantillas sembradas (se esperaban 11)')
        preferencias = con.execute('SELECT COUNT(*) FROM preferencias_sinc').fetchone()[0]
        exigir(preferencias >= 1, 'faltan las preferencias sembradas')
        muestras = con.execute('SELECT COUNT(*) FROM muestras').fetchone()[0]
        exigir(muestras == 0, 'la base nueva trae muestras')
        version_esquema = con.execute('PRAGMA user_version').fetchone()[0]
    finally:
        con.close()
    return {'tablas': len(tablas), 'tablas_schema': len(esperadas), 'plantillas': plantillas,
            'preferencias': preferencias, 'user_version': version_esquema}


def comprobar_perezosos(cargados_en_listo: dict[str, bool]) -> dict[str, Any]:
    exigir(not cargados_en_listo.get('PIL'), 'PIL ya estaba cargado en «listo» (C3)')
    exigir(not cargados_en_listo.get('webview') and not cargados_en_listo.get('clr'),
           'pywebview o el CLR ya estaban cargados en «listo»')
    return {'cargados_en_listo': [m for m, si in cargados_en_listo.items() if si]}


def comprobar_qr() -> dict[str, Any]:
    from creatorhub.lan import qr
    png = qr.png(TEXTO_QR)
    exigir(png[:8] == b'\x89PNG\r\n\x1a\n', 'el QR no es un PNG')
    return {'bytes': len(png)}


def comprobar_pil() -> dict[str, Any]:
    import io
    ya = 'PIL' in sys.modules
    t0 = time.perf_counter()
    from PIL import Image                                            # C3: aparte, después de «listo»
    t_pil = (time.perf_counter() - t0) * 1000.0
    salida = io.BytesIO()
    Image.new('RGB', (8, 8), (12, 15, 13)).save(salida, format='WEBP', quality=60)
    exigir(salida.getvalue()[:4] == b'RIFF', 'Pillow no codificó WebP')
    import PIL
    return {'t_pil_ms': round(t_pil), 'version': PIL.__version__, 'ya_cargado': ya}


def comprobar_edgechromium() -> dict[str, Any]:
    t0 = time.perf_counter()
    import webview.platforms.edgechromium  # noqa: F401  (CLR de .NET + Microsoft.Web.WebView2.Core)
    t = (time.perf_counter() - t0) * 1000.0
    from webview._version import __version__ as version_pywebview
    from creatorhub.plataforma.windows import webview2
    return {'t_edgechromium_ms': round(t), 'pywebview': version_pywebview, 'webview2': webview2.version_instalada()}


def comprobar_dpapi() -> dict[str, Any]:
    from creatorhub.cripto import dpapi
    claro = os.urandom(48)
    blob = dpapi.proteger(claro, ENTROPIA_PRUEBA)
    exigir(blob != claro and dpapi.desproteger(blob, ENTROPIA_PRUEBA) == claro, 'DPAPI no devolvió lo cifrado')
    try:
        dpapi.desproteger(blob, ENTROPIA_PRUEBA + b'x')
        otra_entropia_rechazada = False
    except OSError:
        otra_entropia_rechazada = True
    exigir(otra_entropia_rechazada, 'DPAPI aceptó otra entropía')
    return {'bytes': len(blob)}


def comprobar_cng() -> dict[str, Any]:
    from creatorhub.cripto import cng_aesgcm
    clave, nonce, claro, aad = os.urandom(32), os.urandom(12), b'Corte autoprueba CNG', b'ch'
    cifrado = cng_aesgcm.cifrar(clave, nonce, claro, aad)
    exigir(cng_aesgcm.descifrar(clave, nonce, cifrado, aad) == claro, 'AES-GCM (CNG) no devolvió lo cifrado')
    alterado = cifrado[:-1] + bytes([cifrado[-1] ^ 1])
    try:
        cng_aesgcm.descifrar(clave, nonce, alterado, aad)
        rechazado = False
    except OSError:
        rechazado = True
    exigir(rechazado, 'AES-GCM (CNG) aceptó una etiqueta alterada')
    return {'bytes': len(cifrado)}


def comprobar_identidad_tls(rutas: Any) -> dict[str, Any]:
    import ssl
    from creatorhub.cripto import tls_cng
    t0 = time.perf_counter()
    huella = tls_cng.generar_y_guardar(rutas.secretos, rutas.tls)
    contexto, huella2 = tls_cng.contexto_servidor(rutas.secretos, rutas.tls)
    t = (time.perf_counter() - t0) * 1000.0
    exigir(isinstance(contexto, ssl.SSLContext), 'no se obtuvo un SSLContext')
    exigir(re.fullmatch(r'[0-9a-f]{64}', huella or '') and huella == huella2, 'huella TLS inválida')
    return {'t_identidad_tls_ms': round(t), 'openssl': ssl.OPENSSL_VERSION}


def _a100ns(ft: Any) -> int:
    return (ft.dwHighDateTime << 32) | ft.dwLowDateTime


def cpu_ms_hilo() -> float | None:
    """CPU (usuario + núcleo) que lleva gastada el hilo actual, en ms (GetThreadTimes; resolución ~15.6 ms)."""
    try:
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        k32.GetCurrentThread.restype = wintypes.HANDLE
        k32.GetThreadTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        k32.GetThreadTimes.restype = wintypes.BOOL
        creado, salida, nucleo, usuario = (wintypes.FILETIME() for _ in range(4))
        if not k32.GetThreadTimes(k32.GetCurrentThread(), ctypes.byref(creado), ctypes.byref(salida),
                                  ctypes.byref(nucleo), ctypes.byref(usuario)):
            return None
        return (_a100ns(nucleo) + _a100ns(usuario)) / 10_000
    except (OSError, AttributeError):
        return None


def referencia_cpu(vueltas: int = 1_000_000) -> dict[str, int | None]:
    """Contexto para leer los tiempos: un bucle fijo de Python medido con el reloj y con la CPU del hilo. En una PC sin
    carga ronda 30–60 ms y ambas cifras coinciden. Si el reloj sale muy por encima de la CPU, el proceso esperó turno
    (la CPU estaba ocupada); si las dos salen 3–10 veces más altas, la CPU corre lenta (frecuencia baja por carga o
    temperatura). En ambos casos los tiempos de arranque también vienen inflados."""
    c0 = cpu_ms_hilo()
    t0 = time.perf_counter()
    x = 0
    for i in range(vueltas):
        x += i
    reloj = round((time.perf_counter() - t0) * 1000)
    c1 = cpu_ms_hilo()
    return {'reloj_ms': reloj, 'cpu_hilo_ms': None if c0 is None or c1 is None else round(c1 - c0)}


def referencia_cpu_ms(vueltas: int = 1_000_000) -> int:
    """El bucle de `referencia_cpu()`, solo el reloj (ms)."""
    return int(referencia_cpu(vueltas)['reloj_ms'] or 0)


def cpu_ms_proceso_detalle() -> dict[str, int] | None:
    """CPU que lleva gastada este proceso (todos los hilos), en ms, separada en usuario y núcleo (GetProcessTimes). A
    diferencia de las marcas de reloj, casi no crece cuando otros procesos compiten por la CPU: sirve para separar «el
    arranque es pesado» de «la PC está saturada». Mucho tiempo de núcleo suele ser paginación (PC sin memoria libre)."""
    try:
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        k32.GetProcessTimes.restype = wintypes.BOOL
        creado, salida, nucleo, usuario = (wintypes.FILETIME() for _ in range(4))
        if not k32.GetProcessTimes(k32.GetCurrentProcess(), ctypes.byref(creado), ctypes.byref(salida),
                                   ctypes.byref(nucleo), ctypes.byref(usuario)):
            return None
        return {'usuario': _a100ns(usuario) // 10_000, 'nucleo': _a100ns(nucleo) // 10_000}
    except (OSError, AttributeError):
        return None


def cpu_ms_proceso() -> int | None:
    """CPU total (usuario + núcleo, todos los hilos) que lleva gastada este proceso, en ms."""
    d = cpu_ms_proceso_detalle()
    return None if d is None else d['usuario'] + d['nucleo']


def tiempos_sistema() -> tuple[int, int] | None:
    """(ocupado, total) acumulados de TODAS las CPU de la PC, en unidades de 100 ns (GetSystemTimes). El tiempo de
    núcleo que devuelve Windows ya incluye el inactivo."""
    try:
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        k32.GetSystemTimes.argtypes = [ctypes.POINTER(wintypes.FILETIME)] * 3
        k32.GetSystemTimes.restype = wintypes.BOOL
        inactivo, nucleo, usuario = (wintypes.FILETIME() for _ in range(3))
        if not k32.GetSystemTimes(ctypes.byref(inactivo), ctypes.byref(nucleo), ctypes.byref(usuario)):
            return None
        total = _a100ns(nucleo) + _a100ns(usuario)
        return total - _a100ns(inactivo), total
    except (OSError, AttributeError):
        return None


def cpu_sistema_pct(antes: tuple[int, int] | None, despues: tuple[int, int] | None) -> int | None:
    """% de ocupación de la CPU de toda la PC entre dos muestras de `tiempos_sistema()`."""
    if not antes or not despues or despues[1] - antes[1] <= 0:
        return None
    return max(0, min(100, round(100 * (despues[0] - antes[0]) / (despues[1] - antes[1]))))


def piso_interprete_ms(veces: int = 3) -> list[int] | None:
    """Solo desde el código (en el exe no hay un intérprete aparte): lo que tarda en abrir y cerrar un intérprete vacío
    (`python -I -S -c pass`, el ejecutable base y no el lanzador del venv). En una PC sin carga son unos 20–60 ms; es el
    piso del momento: ningún arranque medido desde la creación del proceso puede bajar de ahí."""
    if getattr(sys, 'frozen', False):
        return None
    import subprocess
    exe = getattr(sys, '_base_executable', None) or sys.executable
    tiempos: list[int] = []
    for _ in range(veces):
        t0 = time.perf_counter()
        try:
            subprocess.run([exe, '-I', '-S', '-c', 'pass'], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=60, check=False,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except (OSError, subprocess.SubprocessError):
            return tiempos or None
        tiempos.append(round((time.perf_counter() - t0) * 1000))
    return tiempos


# Umbrales para decir «la PC estaba saturada» (holgados: 2–3 veces lo normal sin carga).
SATURADA_CPU_SISTEMA_PCT = 90
SATURADA_PISO_MS = 150
SATURADA_REFERENCIA_MS = 120
SATURADA_FISICA_LIBRE_MB = 1024
SATURADA_COMPROMISO_LIBRE_MB = 2048


def diagnosticar(informe: dict[str, Any]) -> str | None:
    """Texto para quien lea autoprueba.json cuando `t_hub_listo_ms` quedó fuera del tope: si la PC estaba saturada (y
    por qué) o si hay que revisar los imports antes de «listo». None si quedó dentro del tope o no se midió."""
    if informe.get('dentro_del_tope') is not False:
        return None
    causas: list[str] = []
    cpu = informe.get('cpu_sistema_pct')
    if isinstance(cpu, int) and cpu >= SATURADA_CPU_SISTEMA_PCT:
        causas.append(f'la CPU de toda la PC estuvo ocupada al {cpu} % entre main() y «listo»')
    piso = informe.get('piso_interprete_ms')
    if piso and min(piso) > SATURADA_PISO_MS:
        causas.append(f'un intérprete de Python vacío tardó {min(piso)} ms en abrir y cerrar (20–60 ms sin carga)')
    ref = informe.get('referencia_cpu_listo_ms')                     # la del final puede caer en otro momento
    if isinstance(ref, int) and ref > SATURADA_REFERENCIA_MS:
        causas.append(f'el bucle de referencia tardó {ref} ms justo después de «listo» (30–60 ms sin carga)')
    mem = informe.get('memoria') or {}
    libre, compromiso = mem.get('fisica_libre_mb'), mem.get('compromiso_libre_mb')
    if (isinstance(libre, int) and libre < SATURADA_FISICA_LIBRE_MB) or \
            (isinstance(compromiso, int) and compromiso < SATURADA_COMPROMISO_LIBRE_MB):
        causas.append(f'quedaban {libre} MB de memoria física y {compromiso} MB de compromiso libres')
    if causas:
        return ('Fuera del tope con la PC saturada: ' + '; '.join(causas) +
                '. Estas cifras no sirven para juzgar el arranque: repite la autoprueba con la PC sin carga.')
    return ('Fuera del tope sin señales de saturación: revisa lo que se importa antes de «listo» '
            '(python -X importtime -m creatorhub --autoprueba).')


def resumen(informe: dict[str, Any], destino: str) -> str:
    """Una línea para la consola y el registro."""
    tope = informe.get('tope_hub_listo_ms', TOPE_HUB_LISTO_MS)
    dentro = {True: 'dentro', False: 'FUERA'}.get(informe.get('dentro_del_tope'), 'sin medir')
    fallas = [n for n, c in (informe.get('comprobaciones') or {}).items() if not c.get('ok')]
    linea = (f"Autoprueba de Corte {'OK' if informe.get('ok') else 'CON FALLAS'}: hub listo en "
             f"{informe.get('t_hub_listo_ms')} ms ({dentro} del tope de {tope} ms) · PIL {informe.get('t_pil_ms')} ms · "
             f"CLR {informe.get('t_edgechromium_ms')} ms · TLS {informe.get('t_identidad_tls_ms')} ms · "
             f"CPU de la PC {informe.get('cpu_sistema_pct')} % · informe: {destino}")
    if fallas or informe.get('error'):
        linea += f" · fallas: {', '.join(fallas) or informe.get('error')}"
    if informe.get('diagnostico'):
        linea += '\n' + informe['diagnostico']
    return linea


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [('dwLength', wintypes.DWORD), ('dwMemoryLoad', wintypes.DWORD), ('ullTotalPhys', ctypes.c_ulonglong),
                ('ullAvailPhys', ctypes.c_ulonglong), ('ullTotalPageFile', ctypes.c_ulonglong),
                ('ullAvailPageFile', ctypes.c_ulonglong), ('ullTotalVirtual', ctypes.c_ulonglong),
                ('ullAvailVirtual', ctypes.c_ulonglong), ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]


def memoria_libre() -> dict[str, int] | None:
    """Contexto de la PC al medir: memoria física libre y compromiso (RAM + archivo de paginación) libre, en MB."""
    try:
        estado = _MEMORYSTATUSEX()
        estado.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        if not ctypes.WinDLL('kernel32').GlobalMemoryStatusEx(ctypes.byref(estado)):
            return None
        mb = 1024 * 1024
        return {'carga_pct': int(estado.dwMemoryLoad), 'fisica_libre_mb': estado.ullAvailPhys // mb,
                'fisica_total_mb': estado.ullTotalPhys // mb, 'compromiso_libre_mb': estado.ullAvailPageFile // mb,
                'compromiso_total_mb': estado.ullTotalPageFile // mb}
    except (OSError, AttributeError):
        return None


# ---------------------------------------------------------------------- corrida
def escribir_informe(carpeta: str, informe: dict[str, Any]) -> str:
    destino = os.path.join(carpeta, INFORME)
    with open(destino + '.nuevo', 'w', encoding='utf-8') as f:
        json.dump(informe, f, ensure_ascii=False, indent=2)
    os.replace(destino + '.nuevo', destino)
    return destino


def _guardar_parcial(carpeta: str, informe: dict[str, Any]) -> None:
    try:
        escribir_informe(carpeta, {**informe, 'ok': False, 't_total_ms': ms_desde_inicio_proceso()})
    except OSError:
        pass


def correr(datos: str | None = None, ahora: int | None = None, puerto: int | None = None, t_main_ms: int | None = None,
           depurar: bool = False) -> int:
    """→ 0 si todo pasó; 1 si algo falló; 3 si otra autoprueba no soltó su mutex en 60 s."""
    marcas: dict[str, int | None] = {'correr': ms_desde_inicio_proceso(), 'previo_import_hub': None,
                                     'previo_iniciar_hub': None}
    t_main_ms = marcas['correr'] if t_main_ms is None else t_main_ms
    sistema_main = tiempos_sistema()
    cpu: dict[str, int | None] = {'main': cpu_ms_proceso(), 'import': None, 'listo': None, 'listo_usuario': None,
                                  'listo_nucleo': None}
    consola = sys.stderr                                              # None en el exe sin consola
    carpeta = os.path.abspath(datos or CARPETA)
    mutex = _MutexAutoprueba()
    if not mutex.tomar():
        return 3
    informe: dict[str, Any] = {'version': config.VERSION, 'ok': False, 't_main_ms': t_main_ms, 't_import_ms': None,
                               't_hub_listo_ms': None, 't_pil_ms': None, 't_edgechromium_ms': None,
                               't_identidad_tls_ms': None, 't_total_ms': None,
                               'tope_hub_listo_ms': TOPE_HUB_LISTO_MS, 'dentro_del_tope': None, 'marcas_ms': marcas,
                               't_hub_listo_cpu_ms': None, 'cpu_ms': cpu, 'cpu_sistema_pct': None,
                               'referencia_cpu_listo_ms': None, 'referencia_cpu_ms': None,
                               'referencia_cpu_hilo_ms': None, 'piso_interprete_ms': None, 'memoria': None,
                               'modulos_en_listo': None, 'diagnostico': None, 'carpeta': carpeta,
                               'comprobaciones': {}, 'en_curso': None, 'error': None}
    hub: Any = None
    registro: Any = None
    linea_resumen: str | None = None
    try:
        preparar_carpeta(carpeta, es_la_de_omision=datos is None)
    except CarpetaAjena as e:                                        # nada se escribe en una carpeta ajena
        mutex.soltar()
        if sys.stderr is not None:
            sys.stderr.write(f'Corte: {e}\n')
        return 1
    try:
        marcas['previo_import_hub'] = ms_desde_inicio_proceso()
        from creatorhub import registro
        from creatorhub.hub import iniciar_hub
        from creatorhub.interfaces import OpcionesHub
        informe['t_import_ms'] = ms_desde_inicio_proceso()
        cpu['import'] = cpu_ms_proceso()
        rutas = config.rutas_para('autoprueba', carpeta)
        existia_antes = os.path.exists(rutas.db)
        registro.configurar_registro(rutas, depurar=depurar)
        marcas['previo_iniciar_hub'] = ms_desde_inicio_proceso()
        hub = iniciar_hub(OpcionesHub(modo='autoprueba', puerto_ui=0 if puerto is None else puerto, raiz_datos=carpeta,
                                      sin_lan=True, sync_al_iniciar=False, ahora_fijo=ahora))
        informe['t_hub_listo_ms'] = ms_desde_inicio_proceso()
        detalle = cpu_ms_proceso_detalle()
        sistema_listo = tiempos_sistema()
        if detalle is not None:
            cpu['listo_usuario'], cpu['listo_nucleo'] = detalle['usuario'], detalle['nucleo']
            cpu['listo'] = detalle['usuario'] + detalle['nucleo']
        informe['t_hub_listo_cpu_ms'] = cpu['listo']
        informe['cpu_sistema_pct'] = cpu_sistema_pct(sistema_main, sistema_listo)
        informe['dentro_del_tope'] = informe['t_hub_listo_ms'] <= TOPE_HUB_LISTO_MS
        informe['t_hub_listo_interno_ms'] = round(getattr(hub, 't_listo_ms', 0) or 0)
        informe['modulos_en_listo'] = len(sys.modules)
        cargados_en_listo = {m: m in sys.modules for m in ('PIL', 'webview', 'clr')}
        informe['referencia_cpu_listo_ms'] = referencia_cpu_ms()       # después de «listo»: no suma a t_hub_listo_ms
        _log.info('Autoprueba: hub listo en %s ms desde la creación del proceso (CPU %s ms; ref. %s ms)',
                  informe['t_hub_listo_ms'], informe['t_hub_listo_cpu_ms'], informe['referencia_cpu_listo_ms'])

        pasos: list[tuple[str, Callable[[], dict[str, Any]]]] = [
            ('salud', lambda: comprobar_salud(hub.puerto_ui)),
            ('sin_activar_http', lambda: comprobar_sin_activar_http(hub.puerto_ui)),
            ('base_nueva', lambda: comprobar_base_nueva(rutas.db, existia_antes)),
            ('pil_perezoso', lambda: comprobar_perezosos(cargados_en_listo)),
            ('qr', comprobar_qr),
            ('pil', comprobar_pil),
            ('edgechromium', comprobar_edgechromium),
            ('dpapi', comprobar_dpapi),
            ('cng', comprobar_cng),
            ('identidad_tls', lambda: comprobar_identidad_tls(rutas)),
        ]
        todo_ok = True
        for nombre, paso in pasos:
            # Informe parcial antes de cada paso (ok=false, en_curso=<paso>): si el proceso muere sin poder escribir (p. ej.
            # el CLR de .NET se cae con OutOfMemoryException en una PC sin memoria libre), queda dónde se detuvo.
            informe['en_curso'] = nombre
            _guardar_parcial(carpeta, informe)
            try:
                resultado = paso()
                informe['comprobaciones'][nombre] = {'ok': True, **resultado}
            except Exception as e:  # noqa: BLE001
                todo_ok = False
                mensaje = str(e) if isinstance(e, FalloAutoprueba) else type(e).__name__
                informe['comprobaciones'][nombre] = {'ok': False, 'error': mensaje}
                _log.error('Autoprueba: %s falló (%s)', nombre, mensaje)
        informe['en_curso'] = None
        c = informe['comprobaciones']
        informe['t_pil_ms'] = c.get('pil', {}).get('t_pil_ms')
        informe['t_edgechromium_ms'] = c.get('edgechromium', {}).get('t_edgechromium_ms')
        informe['t_identidad_tls_ms'] = c.get('identidad_tls', {}).get('t_identidad_tls_ms')
        informe['ok'] = todo_ok
        try:                                                          # contexto: nunca cambia `ok`
            referencia = referencia_cpu()
            informe['referencia_cpu_ms'] = referencia['reloj_ms']
            informe['referencia_cpu_hilo_ms'] = referencia['cpu_hilo_ms']
            informe['memoria'] = memoria_libre()
            informe['piso_interprete_ms'] = piso_interprete_ms()
            informe['diagnostico'] = diagnosticar(informe)
        except Exception:  # noqa: BLE001
            _log.exception('Autoprueba: no se pudo medir el contexto de la PC')
    except Exception as e:  # noqa: BLE001
        informe['error'] = str(e) if isinstance(e, FalloAutoprueba) else type(e).__name__
        _log.exception('La autoprueba no pudo arrancar el hub')
    finally:
        if hub is not None:
            try:
                hub.detener(3.0)
            except Exception:  # noqa: BLE001
                _log.exception('Error al detener el hub de la autoprueba')
        informe['t_total_ms'] = ms_desde_inicio_proceso()
        destino = os.path.join(carpeta, INFORME)
        try:
            os.makedirs(carpeta, exist_ok=True)
            destino = escribir_informe(carpeta, informe)
        except OSError:
            informe['ok'] = False
        try:
            linea_resumen = resumen(informe, destino)
            _log.info('%s', linea_resumen)
        except Exception:  # noqa: BLE001  (el resumen nunca tumba la autoprueba)
            linea_resumen = None
        if registro is not None:
            registro.cerrar_registro()
        borrar_apartadas(carpeta)
        mutex.soltar()
    if consola is not None and linea_resumen:
        try:
            consola.write(linea_resumen + '\n')
            consola.flush()
        except (OSError, ValueError, AttributeError, UnicodeError):
            pass
    return 0 if informe['ok'] else 1
