"""Reglas de firewall con UNA UAC (spec 04 §C.10). Nunca se ejecuta con privilegios un archivo que el usuario pueda
modificar: el script es esta constante (va dentro del PYZ del exe) y viaja como -EncodedCommand a powershell.exe de System32."""
import base64
import ctypes
import os
import sys
from ctypes import wintypes

_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$env:PSModulePath = '@@MODULOS@@'
Import-Module NetSecurity, NetConnection
$Exe = '@@EXE@@'
$Perfiles = @(@@PERFILES@@)
$Indice = @@INDICE@@
$RedPrivada = $@@RED_PRIVADA@@
Get-NetFirewallApplicationFilter -Program $Exe -ErrorAction SilentlyContinue | Get-NetFirewallRule -ErrorAction SilentlyContinue |
    Where-Object { $_.Direction -eq 'Inbound' -and $_.Action -eq 'Block' } | Remove-NetFirewallRule
Get-NetFirewallRule -Group 'Corte' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName 'Corte - celular (TCP 39230-39239)' -Group 'Corte' -Direction Inbound -Action Allow -Program $Exe -Protocol TCP -LocalPort '39230-39239' -RemoteAddress LocalSubnet -Profile $Perfiles | Out-Null
New-NetFirewallRule -DisplayName 'Corte - descubrimiento (UDP 39231)' -Group 'Corte' -Direction Inbound -Action Allow -Program $Exe -Protocol UDP -LocalPort 39231 -RemoteAddress LocalSubnet -Profile $Perfiles | Out-Null
if ($RedPrivada -and $Indice -ge 0) { Set-NetConnectionProfile -InterfaceIndex $Indice -NetworkCategory Private }
exit 0
"""
PERFILES_VALIDOS = ("Private", "Public")


def directorio_sistema() -> str:
    """C:\\Windows\\System32 desde la API (no desde variables de entorno, que el usuario controla)."""
    buf = ctypes.create_unicode_buffer(260)
    if not ctypes.WinDLL("kernel32").GetSystemDirectoryW(buf, 260):
        raise OSError("GetSystemDirectoryW falló")
    return buf.value


def construir(exe: str, perfiles=("Private",), indice=None, red_privada=False):
    """-> (powershell.exe absoluto, parámetros). Valida TODO antes de armar el texto que correrá elevado."""
    if os.path.normcase(os.path.abspath(exe)) != os.path.normcase(os.path.abspath(sys.executable)):
        raise ValueError("solo se configura el exe de este mismo proceso")
    if any(c in exe for c in "\r\n\0") or not os.path.isfile(exe):
        raise ValueError("ruta de exe inválida")
    perfiles = tuple(perfiles)
    if not perfiles or len(set(perfiles)) != len(perfiles) or any(p not in PERFILES_VALIDOS for p in perfiles):
        raise ValueError("perfiles inválidos")
    if indice is not None and type(indice) is not int:
        raise ValueError("el índice de interfaz debe ser int")
    if red_privada and (indice is None or indice < 0):
        raise ValueError("para marcar la red como privada hace falta su índice")
    sistema = directorio_sistema()
    modulos = os.path.join(sistema, "WindowsPowerShell", "v1.0", "Modules")
    texto = (_SCRIPT.replace("@@MODULOS@@", modulos.replace("'", "''"))
             .replace("@@PERFILES@@", ",".join(f"'{p}'" for p in perfiles))
             .replace("@@INDICE@@", str(indice if indice is not None else -1))
             .replace("@@RED_PRIVADA@@", "true" if red_privada else "false")
             .replace("@@EXE@@", exe.replace("'", "''")))      # el único valor externo va al final y escapado
    b64 = base64.b64encode(texto.encode("utf-16-le")).decode("ascii")
    return (os.path.join(sistema, "WindowsPowerShell", "v1.0", "powershell.exe"),
            "-NoProfile -NonInteractive -WindowStyle Hidden -EncodedCommand " + b64)


class _SEI(ctypes.Structure):                                 # SHELLEXECUTEINFOW
    _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
                ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                ("dwHotKey", wintypes.DWORD), ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]


def _lanzar(archivo: str, parametros: str, verbo: str, espera_s: int = 120, hwnd=None) -> int:
    """-> código de salida del proceso, o el error de ShellExecuteExW (1223 = el usuario canceló la UAC)."""
    sh = ctypes.WinDLL("shell32", use_last_error=True)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    sh.ShellExecuteExW.argtypes = [ctypes.POINTER(_SEI)]
    k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    sei = _SEI(cbSize=ctypes.sizeof(_SEI), fMask=0x00000040 | 0x00000400,   # NOCLOSEPROCESS | FLAG_NO_UI
               hwnd=hwnd, lpVerb=verbo, lpFile=archivo, lpParameters=parametros,
               lpDirectory=os.path.dirname(archivo), nShow=0)
    if not sh.ShellExecuteExW(ctypes.byref(sei)):
        return ctypes.get_last_error()
    try:
        if k32.WaitForSingleObject(sei.hProcess, espera_s * 1000) != 0:
            return 258                                           # WAIT_TIMEOUT
        codigo = wintypes.DWORD()
        k32.GetExitCodeProcess(sei.hProcess, ctypes.byref(codigo))
        return codigo.value
    finally:
        k32.CloseHandle(sei.hProcess)


def configurar(perfiles=("Private",), indice=None, red_privada=False, hwnd=None) -> int:
    """Una UAC. 0 = listo · 1223 = canceló · otro = falló. Después: repetir el diagnóstico (§C.10, paso 4)."""
    archivo, parametros = construir(sys.executable, perfiles, indice, red_privada)
    return _lanzar(archivo, parametros, "runas", hwnd=hwnd)
