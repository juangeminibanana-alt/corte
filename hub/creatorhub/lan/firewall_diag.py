"""Diagnóstico del firewall de Windows SIN administrador (04 §C.10 paso 1–2; BUILD C28; contrato.ts DiagnosticoFirewall).

Corre el script de 04 §C.10 (reglas de entrada habilitadas del programa + categoría de la red conectada) con el
`powershell.exe` de System32 (ruta pedida a la API, no a variables de entorno), `-NoProfile -NonInteractive`, sin
ventana y con tope de 20 s (medido: 4–7 s). Se pasa como `-EncodedCommand` (mismo script; evita problemas de comillas
de la línea de comandos de PowerShell 5.1). El JSON no depende del idioma: nunca se analiza `netsh`.

Regla «cubre la red actual»: algún `permitir` cuyo texto sea `Any` o contenga el perfil actual («Private, Public»
contiene Public) y ningún `bloquear` que lo cubra. Estados (EstadoFirewall):
- `bien`: la regla cubre la red → sin aviso.
- `red_publica`: la red es Pública y no está cubierta (aunque haya bloqueos: las dos opciones los quitan).
- `bloqueado`: red privada o de dominio con una regla de bloqueo que la cubre → «Arreglar».
- `desconocido`: sin reglas todavía (Windows preguntará), sin red conectada o el diagnóstico no pudo correr.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from ..interfaces import Json

_log = logging.getLogger('creatorhub.lan.firewall')

TOPE_S = 20
CREATE_NO_WINDOW = 0x08000000

# Paso 1 de 04 §C.10 (literal), con el exe ya validado como único valor externo (escapado como en firewall.py).
SCRIPT_DIAGNOSTICO = r"""
$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$exe = '@@EXE@@'
$r = Get-NetFirewallApplicationFilter -Program $exe -EA SilentlyContinue | Get-NetFirewallRule -EA SilentlyContinue |
     Where-Object { $_.Direction -eq 'Inbound' -and $_.Enabled -eq 'True' }
$red = Get-NetConnectionProfile | Where-Object IPv4Connectivity -ne 'Disconnected' | Select-Object -First 1
[pscustomobject]@{ permitir = @($r | ? Action -eq 'Allow' | % { "$($_.Profile)" })
                   bloquear = @($r | ? Action -eq 'Block' | % { "$($_.Profile)" })
                   red = "$($red.NetworkCategory)"; indice = $red.InterfaceIndex } | ConvertTo-Json -Compress
"""

# Textos de 04 §C.10 y 01 §4.14 C (español de México; «Wi‑Fi» con guion que no se corta, como en 01).
MENSAJES = {
    'bloqueado': 'Windows está bloqueando a Corte en esta red.',
    'red_publica': 'Tu Wi‑Fi está marcada como Pública. Para que tu celular encuentre esta PC, elige una opción:',
    'sin_reglas': 'Windows te preguntará si Corte puede usar la red. Elige “Redes privadas”.',
    'sin_diagnostico': 'No pudimos revisar el firewall de Windows. Si tu celular no encuentra esta PC, revisa que los '
                       'dos estén en la misma red Wi‑Fi.',
}
REDES = ('Public', 'Private', 'DomainAuthenticated')


@dataclass
class Diagnostico:
    estado: str
    red: str | None
    mensaje: str | None
    indice: int | None = None                        # índice de la interfaz (para marcar la red como privada)
    permitir: list[str] = field(default_factory=list)
    bloquear: list[str] = field(default_factory=list)
    duracion_s: float = 0.0

    def contrato(self) -> Json:
        """DiagnosticoFirewall (solo las claves del contrato)."""
        return {'estado': self.estado, 'red': self.red, 'mensaje': self.mensaje}


def _perfil(red: str) -> str:
    return 'Domain' if red == 'DomainAuthenticated' else red


def _cubre(texto: str, perfil: str) -> bool:
    partes = [p.strip() for p in str(texto).split(',')]
    return 'Any' in partes or perfil in partes


def evaluar(permitir: list[str], bloquear: list[str], red: str | None, indice: int | None = None) -> Diagnostico:
    """Aplica la regla «cubre la red actual» de 04 §C.10."""
    if red not in REDES:
        return Diagnostico('desconocido', None, MENSAJES['sin_diagnostico'], None, list(permitir), list(bloquear))
    perfil = _perfil(red)
    bloqueada = any(_cubre(b, perfil) for b in bloquear)
    permitida = any(_cubre(p, perfil) for p in permitir)
    if permitida and not bloqueada:
        estado, mensaje = 'bien', None
    elif red == 'Public':
        estado, mensaje = 'red_publica', MENSAJES['red_publica']
    elif bloqueada:
        estado, mensaje = 'bloqueado', MENSAJES['bloqueado']
    else:
        estado, mensaje = 'desconocido', MENSAJES['sin_reglas']
    return Diagnostico(estado, red, mensaje, indice, list(permitir), list(bloquear))


def _lista(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [v] if v else []
    if isinstance(v, list):
        return [str(x) for x in v if x is not None and str(x)]
    return []


def interpretar(salida: str) -> Diagnostico:
    """JSON del script -> Diagnostico. Lo ilegible es 'desconocido'."""
    try:
        linea = next(x for x in reversed(salida.strip().splitlines()) if x.strip().startswith('{'))
        d = json.loads(linea)
    except (StopIteration, ValueError):
        return evaluar([], [], None)
    if not isinstance(d, dict):
        return evaluar([], [], None)
    red = d.get('red') if d.get('red') in REDES else None
    indice = d.get('indice')
    indice = indice if type(indice) is int else None
    return evaluar(_lista(d.get('permitir')), _lista(d.get('bloquear')), red, indice)


def directorio_sistema() -> str:
    from .firewall import directorio_sistema as _ds
    return _ds()


def powershell() -> str:
    return os.path.join(directorio_sistema(), 'WindowsPowerShell', 'v1.0', 'powershell.exe')


def texto_script(exe: str) -> str:
    if any(c in exe for c in '\r\n\0'):
        raise ValueError('ruta de exe inválida')
    return SCRIPT_DIAGNOSTICO.replace('@@EXE@@', exe.replace("'", "''"))


def ejecutar_powershell(texto: str, tope_s: float = TOPE_S) -> tuple[int, str]:
    """Corre `texto` con el powershell.exe de System32, sin perfil, sin ventana. -> (código, stdout)."""
    b64 = base64.b64encode(texto.encode('utf-16-le')).decode('ascii')
    r = subprocess.run([powershell(), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                        '-EncodedCommand', b64], capture_output=True, timeout=tope_s, creationflags=CREATE_NO_WINDOW,
                       stdin=subprocess.DEVNULL, cwd=directorio_sistema())
    return r.returncode, r.stdout.decode('utf-8', 'replace')


def diagnosticar(exe: str | None = None, ejecutar: Callable[[str], tuple[int, str]] | None = None) -> Diagnostico:
    """Diagnóstico sin administrador (4–7 s). Nunca lanza: si algo falla, 'desconocido'."""
    t0 = time.monotonic()
    try:
        _, salida = (ejecutar or ejecutar_powershell)(texto_script(exe or sys.executable))
        d = interpretar(salida)
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        _log.warning('No se pudo diagnosticar el firewall (%s)', type(e).__name__)
        d = evaluar([], [], None)
    d.duracion_s = time.monotonic() - t0
    _log.info('Firewall: %s (red %s) en %.1f s', d.estado, d.red, d.duracion_s)
    return d


def perfiles_para(opcion: str, diag: Diagnostico) -> tuple[tuple[str, ...], bool]:
    """FirewallRequest.opcion -> (perfiles, marcar la red como privada) para firewall.configurar (04 §C.10 paso 2)."""
    if opcion == 'privada':                          # (a) «Es mi red de casa: márcala como privada»
        return ('Private',), True
    if opcion == 'publica_subred':                   # (b) «Dejarla como pública y permitir solo mi red local»
        return ('Private', 'Public'), False
    if opcion == 'arreglar':                         # estado 'bloqueado': quitar bloqueos y crear reglas
        return (('Private', 'Public') if diag.red == 'Public' else ('Private',)), False
    raise ValueError('opción de firewall desconocida')
