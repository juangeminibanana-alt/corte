"""Punto de entrada de Corte: `CreatorHub.exe` (PyInstaller lo corre como script) y `python -m creatorhub` (desde hub\\).

    CreatorHub.exe [--inicio-windows|--depurar|--autoprueba|--medir|--salir|--desinstalar]            (04 §A.2)
                   [--demo] [--dev] [--fuente sinteticos|fixtures_reales] [--ahora <epoch>] [--puerto <n>]
                   [--datos <carpeta>] [--ui <carpeta dist>] [--sin-lan]                              (BUILD §6.7)

Secuencia (04 §A.2): AUMID `CreatorHub.App` → banderas (con `sys.frozen`: `--dev`, `--fuente fixtures_reales` y `--ui`
terminan con código 2 y un mensaje claro; `--ahora` solo con `--demo` o `--autoprueba`) → `--salir`/`--desinstalar`/
`--autoprueba` → instancia única (literal de 04 §A.5; si ya hay otra, se le dispara `…Activar` y se sale con 0 sin tocar
datos ni abrir puertos; C40: no existe POST /local/activar) → registro limpio (redirige stdout/stderr con el filtro de
secretos si son None) → ¿WebView2? (MessageBox si falta) → `iniciar_hub(OpcionesHub(...))` → ventana → al cerrar:
`hub.detener(3)` y, como último paso, `instancia.liberar()`.

Códigos de salida: 0 bien (o la otra instancia ya fue activada) · 1 error al arrancar o WebView2 ausente · 2 banderas
inválidas o `--salir` que no terminó a tiempo · 3 otra autoprueba no soltó su mutex.
Nada de pywebview, pythonnet ni PIL antes de «listo» (C3): todo se importa tarde.
"""
from __future__ import annotations

import os
import sys

if __package__ in (None, '') and not getattr(sys, 'frozen', False):
    # `pythonw.exe …\hub\creatorhub\__main__.py` (inicio con Windows desde el código): la carpeta del paquete no debe
    # quedar en sys.path y hub\ sí.
    _paquete = os.path.dirname(os.path.abspath(__file__))
    sys.path[:] = [p for p in sys.path if os.path.normcase(os.path.abspath(p or os.curdir)) != os.path.normcase(_paquete)]
    sys.path.insert(0, os.path.dirname(_paquete))

import ctypes  # noqa: E402
import json  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from typing import Any, Sequence  # noqa: E402

from creatorhub.plataforma.windows import instancia  # noqa: E402  (solo ctypes)

AUMID = 'CreatorHub.App'
CODIGO_OK, CODIGO_ERROR, CODIGO_BANDERAS = 0, 1, 2
NOMBRES_INSTANCIA: dict[str, tuple[str, str, str]] = {
    'real': (instancia.MUTEX, instancia.ACTIVAR, instancia.SALIR),            # Local\CreatorHub.Instancia/.Activar/.Salir
    'demo': ('Local\\CreatorHub.Demo', 'Local\\CreatorHub.Demo.Activar', 'Local\\CreatorHub.Demo.Salir'),   # BUILD §1, 03
}
BANDERAS_SIMPLES = ('--inicio-windows', '--depurar', '--autoprueba', '--medir', '--salir', '--desinstalar', '--demo',
                    '--dev', '--sin-lan')
BANDERAS_CON_VALOR = ('--fuente', '--ahora', '--puerto', '--datos', '--ui')
FUENTES = ('sinteticos', 'fixtures_reales')
TEXTO_ERROR_ARRANQUE = ('Corte no pudo iniciar. Cierra otras ventanas de Corte o reinicia tu PC e inténtalo de nuevo.')

MENSAJES_CONGELADO = {
    'dev': '--dev solo existe al correr Corte desde el código; el programa instalado no lo acepta.',
    'fuente': '--fuente fixtures_reales solo existe al correr Corte desde el código: usa datos privados de desarrollo.',
    'ui': '--ui solo existe al correr Corte desde el código; el programa instalado usa su propia interfaz.',
}


class ErrorBanderas(Exception):
    """Banderas inválidas: el mensaje se muestra tal cual y se sale con código 2."""


@dataclass
class Banderas:
    inicio_windows: bool = False
    depurar: bool = False
    autoprueba: bool = False
    medir: bool = False
    salir: bool = False
    desinstalar: bool = False
    demo: bool = False
    dev: bool = False
    sin_lan: bool = False
    fuente: str | None = None
    ahora: int | None = None
    puerto: int | None = None
    datos: str | None = None
    ui: str | None = None

    @property
    def modo(self) -> str:
        return 'autoprueba' if self.autoprueba else 'demo' if self.demo else 'real'


def _entero(nombre: str, texto: str, minimo: int, maximo: int) -> int:
    try:
        valor = int(texto, 10)
    except ValueError:
        raise ErrorBanderas(f'{nombre} necesita un número entero (recibió «{texto[:40]}»).') from None
    if not minimo <= valor <= maximo:
        raise ErrorBanderas(f'{nombre} fuera de rango ({minimo}–{maximo}).')
    return valor


def parsear(argv: Sequence[str]) -> Banderas:
    b = Banderas()
    vistas: set[str] = set()
    i = 0
    while i < len(argv):
        arg = str(argv[i])
        nombre, igual, valor = arg.partition('=')
        if nombre in BANDERAS_SIMPLES and not igual:
            if nombre in vistas:
                raise ErrorBanderas(f'{nombre} viene repetida.')
            vistas.add(nombre)
            setattr(b, nombre[2:].replace('-', '_'), True)
            i += 1
            continue
        if nombre in BANDERAS_CON_VALOR:
            if nombre in vistas:
                raise ErrorBanderas(f'{nombre} viene repetida.')
            vistas.add(nombre)
            if not igual:
                if i + 1 >= len(argv) or str(argv[i + 1]).startswith('--'):
                    raise ErrorBanderas(f'Falta el valor de {nombre}.')
                valor = str(argv[i + 1])
                i += 1
            i += 1
            if nombre == '--fuente':
                if valor not in FUENTES:
                    raise ErrorBanderas('--fuente acepta «sinteticos» o «fixtures_reales».')
                b.fuente = valor
            elif nombre == '--ahora':
                b.ahora = _entero('--ahora', valor, 1, 32503680000)
            elif nombre == '--puerto':
                b.puerto = _entero('--puerto', valor, 0, 65535)
            elif nombre == '--datos':
                b.datos = valor
            else:
                b.ui = valor
            continue
        raise ErrorBanderas(f'Opción desconocida: {arg[:60]}')
    return b


def validar(b: Banderas, congelado: bool) -> None:
    """Reglas de 04 §A.2 y BUILD §6.7. Con `sys.frozen`, lo de desarrollo termina con código 2."""
    if congelado:
        if b.dev:
            raise ErrorBanderas(MENSAJES_CONGELADO['dev'])
        if b.fuente == 'fixtures_reales':
            raise ErrorBanderas(MENSAJES_CONGELADO['fuente'])
        if b.ui is not None:
            raise ErrorBanderas(MENSAJES_CONGELADO['ui'])
    especiales = [n for n in ('autoprueba', 'medir', 'salir', 'desinstalar') if getattr(b, n)]
    if len(especiales) > 1:
        raise ErrorBanderas('Usa solo una de --autoprueba, --medir, --salir o --desinstalar.')
    if b.demo and b.autoprueba:
        raise ErrorBanderas('--demo y --autoprueba no se combinan.')
    if b.fuente is not None and not b.demo:
        raise ErrorBanderas('--fuente solo se usa con --demo.')
    if b.ahora is not None and not (b.demo or b.autoprueba):
        raise ErrorBanderas('--ahora solo se usa con --demo o --autoprueba.')
    if b.datos is not None and not b.datos.strip():
        raise ErrorBanderas('--datos necesita una carpeta.')
    if b.ui is not None and not os.path.isdir(b.ui):
        raise ErrorBanderas('--ui necesita una carpeta que exista (la salida de npm run build).')


def opciones_hub(b: Banderas, oculta: bool = False) -> Any:
    """OpcionesHub para el arranque con ventana (real, demo o --medir)."""
    from creatorhub.interfaces import OpcionesHub
    return OpcionesHub(
        modo='demo' if b.demo else 'real',
        dev=b.dev,
        ahora_fijo=b.ahora,
        puerto_ui=b.puerto,
        raiz_datos=os.path.abspath(b.datos) if b.datos else None,
        dir_ui=os.path.abspath(b.ui) if b.ui else None,
        sin_lan=True if not b.demo else b.sin_lan or b.medir,
        fuente_demo=b.fuente or 'sinteticos',      # type: ignore[arg-type]
        sync_al_iniciar=False if not b.demo else not b.medir,
        cliente_nube=not b.demo and not b.medir,
        retraso_sync_s=60.0 if oculta else 5.0,   # --inicio-windows con segundo plano: la 1.ª sync espera 60 s
    )


# ---------------------------------------------------------------------- utilidades de Windows
def fijar_aumid() -> None:
    try:
        shell32 = ctypes.WinDLL('shell32')
        shell32.SetCurrentProcessExplicitAppUserModelID.argtypes = [ctypes.c_wchar_p]
        shell32.SetCurrentProcessExplicitAppUserModelID(AUMID)
    except (OSError, AttributeError):
        pass


def permitir_primer_plano() -> None:
    """La 2.ª instancia (que el usuario acaba de abrir y tiene el primer plano) se lo cede a la 1.ª (ASFW_ANY)."""
    try:
        ctypes.WinDLL('user32').AllowSetForegroundWindow(0xFFFFFFFF)
    except (OSError, AttributeError):
        pass


def hay_otra_instancia(nombre_mutex: str) -> bool:
    """¿Ya existe el mutex de la instancia? Solo lo abre con SYNCHRONIZE y lo cierra: no lo crea ni lo posee."""
    try:
        h = instancia.k32.OpenMutexW(0x00100000, False, nombre_mutex)   # SYNCHRONIZE
    except (OSError, AttributeError, ctypes.ArgumentError):
        return False
    if not h:
        return False
    instancia.k32.CloseHandle(h)
    return True


def preparar_activacion(modo: str) -> bool:
    """Si ya hay una instancia del modo, cede el primer plano (ASFW_ANY) JUSTO ANTES de que `tomar_instancia()` le
    señale Activar, para que pueda pasar al frente. La 1.ª instancia no lo llama. → True si había otra."""
    if not hay_otra_instancia(NOMBRES_INSTANCIA[modo][0]):
        return False
    permitir_primer_plano()
    return True


def avisar_consola(mensaje: str) -> None:
    """stderr si existe; en el exe sin consola, la consola que lo lanzó (AttachConsole). Nunca bloquea."""
    flujo = sys.stderr
    if flujo is not None:
        try:
            flujo.write(mensaje + '\n')
            flujo.flush()
            return
        except (OSError, ValueError, AttributeError):
            pass
    try:
        k32 = ctypes.WinDLL('kernel32')
        if k32.AttachConsole(0xFFFFFFFF):                                # ATTACH_PARENT_PROCESS
            try:
                with open('CONOUT$', 'w', encoding='utf-8') as f:
                    f.write('\n' + mensaje + '\n')
            finally:
                k32.FreeConsole()
    except OSError:
        pass


def avisar_error_arranque() -> None:
    if sys.stderr is not None and getattr(sys.stderr, 'isatty', lambda: False)():
        avisar_consola('Corte: ' + TEXTO_ERROR_ARRANQUE)
        return
    if getattr(sys, 'frozen', False):
        from creatorhub.plataforma.windows import webview2
        webview2.mostrar_mensaje('Corte', TEXTO_ERROR_ARRANQUE)
    else:
        avisar_consola('Corte: ' + TEXTO_ERROR_ARRANQUE)


def tomar_instancia(modo: str) -> Any:
    """`instancia.tomar_instancia()` (literal de 04 §A.5) con los nombres del modo: real = Local\\CreatorHub.Instancia;
    demo = Local\\CreatorHub.Demo (puede convivir con la app real). Los nombres se restauran al volver."""
    mutex, activar, salir = NOMBRES_INSTANCIA[modo]
    originales = (instancia.MUTEX, instancia.ACTIVAR, instancia.SALIR)
    instancia.MUTEX, instancia.ACTIVAR, instancia.SALIR = mutex, activar, salir
    try:
        return instancia.tomar_instancia()
    finally:
        instancia.MUTEX, instancia.ACTIVAR, instancia.SALIR = originales


def leer_segundo_plano(ruta_config: str) -> bool | None:
    """AjustesPc.segundo_plano de config.json, solo lectura (sin apartar un archivo dañado: eso lo hace el hub)."""
    try:
        with open(ruta_config, encoding='utf-8') as f:
            datos = json.load(f)
    except (OSError, ValueError):
        return None
    ajustes = datos.get('ajustes_pc') if isinstance(datos, dict) else None
    valor = ajustes.get('segundo_plano') if isinstance(ajustes, dict) else None
    return valor if isinstance(valor, bool) else None


# ---------------------------------------------------------------------- arranque con ventana
def arrancar(b: Banderas) -> int:
    modo = 'demo' if b.demo else 'real'
    preparar_activacion(modo)                                         # solo la 2.ª instancia cede el primer plano
    inst = tomar_instancia(modo)
    if inst is None:
        return CODIGO_OK                                              # la otra instancia recibió «Activar» (C40)
    hub: Any = None
    registro: Any = None
    try:
        import logging

        from creatorhub import config
        from creatorhub import registro as _registro
        rutas = config.rutas_para(modo, os.path.abspath(b.datos) if b.datos else None)
        _registro.configurar_registro(rutas, depurar=b.depurar)    # stdout/stderr None → registro limpio + faulthandler
        registro = _registro
        log = logging.getLogger('creatorhub.main')
        log.info('Corte %s arrancando (modo %s%s%s)', config.VERSION, modo, ', dev' if b.dev else '',
                 ', medir' if b.medir else '')

        from creatorhub.plataforma.windows import webview2
        version_wv2 = webview2.version_instalada()
        if version_wv2 is None:
            webview2.avisar_falta()
            return CODIGO_ERROR
        log.info('WebView2 %s', version_wv2)

        oculta = b.inicio_windows and leer_segundo_plano(rutas.config_json) is True
        from creatorhub.hub import iniciar_hub
        try:
            hub = iniciar_hub(opciones_hub(b, oculta))
        except Exception:  # noqa: BLE001
            log.exception('El hub no pudo arrancar')
            avisar_error_arranque()
            return CODIGO_ERROR
        t_hub_listo_ms = instancia.ms_desde_inicio_proceso()
        if hub.puerto_respaldo:
            log.warning('Puerto %d ocupado; interfaz en %d', config.PUERTO_UI, hub.puerto_ui)

        from creatorhub.plataforma.windows.ventana import ShellVentana
        shell = ShellVentana(hub, rutas, instancia=inst, depurar=b.depurar, oculta=oculta, medir=b.medir,
                             t_hub_listo_ms=t_hub_listo_ms)
        hub.registrar_ganchos(shell)
        return shell.correr()
    finally:
        if hub is not None:
            hub.detener(3.0)
        if registro is not None:
            registro.cerrar_registro()
        inst.liberar()                                                # último paso: `--salir` deja de esperar aquí


def main(argv: Sequence[str] | None = None) -> int:
    t_main_ms = instancia.ms_desde_inicio_proceso()
    argumentos = list(sys.argv[1:] if argv is None else argv)
    fijar_aumid()
    try:
        b = parsear(argumentos)
        validar(b, bool(getattr(sys, 'frozen', False)))
    except ErrorBanderas as e:
        avisar_consola(f'Corte: {e}')
        return CODIGO_BANDERAS
    if b.salir:
        return instancia.pedir_salida()
    if b.desinstalar:
        r = instancia.pedir_salida()
        from creatorhub.plataforma.windows import inicio_windows
        inicio_windows.InicioWindows().borrar()
        return r
    if b.autoprueba:
        from creatorhub.plataforma.windows import autoprueba
        return autoprueba.correr(datos=b.datos, ahora=b.ahora, puerto=b.puerto, t_main_ms=t_main_ms, depurar=b.depurar)
    return arrancar(b)


if __name__ == '__main__':
    sys.exit(main())
