"""Instancia única, activación y salida que se puede esperar (spec 04 §A.5). Solo ctypes."""
import ctypes
from ctypes import wintypes

MUTEX = "Local\\CreatorHub.Instancia"
ACTIVAR = "Local\\CreatorHub.Activar"
SALIR = "Local\\CreatorHub.Salir"
SYNCHRONIZE, EVENT_MODIFY_STATE, ERROR_ALREADY_EXISTS = 0x00100000, 0x0002, 183
WAIT_OBJECT_0, WAIT_ABANDONED, WAIT_TIMEOUT = 0x000, 0x080, 0x102

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
k32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
k32.OpenMutexW.argtypes = k32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
for _f in (k32.CreateMutexW, k32.CreateEventW, k32.OpenMutexW, k32.OpenEventW, k32.GetCurrentProcess):
    _f.restype = wintypes.HANDLE
k32.SetEvent.argtypes = k32.ReleaseMutex.argtypes = k32.CloseHandle.argtypes = [wintypes.HANDLE]
k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
k32.WaitForSingleObject.restype = wintypes.DWORD
k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
k32.GetSystemTimeAsFileTime.argtypes = [ctypes.POINTER(wintypes.FILETIME)]


class Instancia:
    """La crea y la usa SOLO el hilo principal: el mutex queda poseído por ese hilo hasta liberar()."""

    def __init__(self, mutex, activar, salir):
        self.mutex, self.activar, self.salir = mutex, activar, salir

    def liberar(self):
        """Último paso del hilo principal, DESPUÉS de cerrar ventana, servidores, sincronización y base."""
        k32.ReleaseMutex(self.mutex)
        for h in (self.activar, self.salir, self.mutex):
            k32.CloseHandle(h)


def tomar_instancia():
    """-> Instancia, o None si ya hay otra (a la que se le pide volver al frente)."""
    m = k32.CreateMutexW(None, True, MUTEX)               # bInitialOwner=True: lo posee el hilo principal
    if not m:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:   # ya existía: NO se nos otorgó la posesión
        k32.CloseHandle(m)
        _senal(ACTIVAR)
        return None
    activar = k32.CreateEventW(None, False, False, ACTIVAR)   # auto-reset; los dos antes de abrir puertos
    salir = k32.CreateEventW(None, True, False, SALIR)        # manual-reset: lo ven todos los hilos que esperan
    return Instancia(m, activar, salir)


def pedir_salida(espera_ms=15000) -> int:
    """--salir / --desinstalar. 0 = no había instancia o ya terminó · 2 = no terminó a tiempo."""
    m = k32.OpenMutexW(SYNCHRONIZE, False, MUTEX)
    if not m:
        return 0
    try:
        _senal(SALIR)
        r = k32.WaitForSingleObject(m, espera_ms)
        if r in (WAIT_OBJECT_0, WAIT_ABANDONED):          # la instancia lo soltó (o murió sin soltarlo)
            k32.ReleaseMutex(m)                           # al esperar lo adquirimos: se suelta enseguida
            return 0
        return 2
    finally:
        k32.CloseHandle(m)


def _senal(nombre):
    ev = k32.OpenEventW(EVENT_MODIFY_STATE, False, nombre)
    if ev:
        k32.SetEvent(ev)
        k32.CloseHandle(ev)


def ms_desde_inicio_proceso() -> int:
    """Milisegundos desde que Windows creó este proceso (incluye el bootloader de PyInstaller)."""
    creado, x1, x2, x3, ahora = (wintypes.FILETIME() for _ in range(5))
    k32.GetProcessTimes(k32.GetCurrentProcess(), ctypes.byref(creado), ctypes.byref(x1), ctypes.byref(x2), ctypes.byref(x3))
    k32.GetSystemTimeAsFileTime(ctypes.byref(ahora))

    def a100ns(ft):
        return (ft.dwHighDateTime << 32) | ft.dwLowDateTime
    return (a100ns(ahora) - a100ns(creado)) // 10_000
