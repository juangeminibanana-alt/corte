"""Direcciones de la PC en la red local (03 §7.2, §7.4; 04 §C.4; contrato.ts LanEstado.direcciones).

- Solo IPv4 privadas: 10/8, 172.16/12, 192.168/16 (el listener LAN rechaza cualquier otro origen; loopback solo con
  `permitir_loopback`, que usan las pruebas).
- Orden: Wi-Fi primero, después el adaptador con la ruta por defecto (puerta de enlace), luego Ethernet y al final los
  adaptadores virtuales (Hyper-V, VirtualBox, VMware, WSL, VPN…). El QR lleva como máximo las 3 primeras.
- Fuente: `GetAdaptersAddresses` (iphlpapi.dll, ctypes): da el tipo de interfaz, el estado, la descripción y las puertas
  de enlace sin abrir sockets ni tocar la red. Si falla, `getaddrinfo(gethostname())` en el orden que dé Windows.
"""
from __future__ import annotations

import ctypes
import ipaddress
import logging
import socket
from ctypes import wintypes
from dataclasses import dataclass, field

_log = logging.getLogger('creatorhub.lan.red')

REDES_PRIVADAS = tuple(ipaddress.ip_network(r) for r in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))
LOOPBACK = ipaddress.ip_network('127.0.0.0/8')

IF_TIPO_ETHERNET = 6
IF_TIPO_LOOPBACK = 24
IF_TIPO_WIFI = 71
IF_TIPO_TUNEL = 131
IF_OPER_ARRIBA = 1
_PALABRAS_VIRTUAL = ('virtual', 'hyper-v', 'vethernet', 'vmware', 'virtualbox', 'host-only', 'vpn', 'tap-', 'tap ',
                     'wsl', 'docker', 'loopback', 'pseudo', 'npcap', 'zerotier', 'tailscale', 'hamachi', 'wireguard',
                     'bluetooth')


def ip_privada(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return a.version == 4 and any(a in r for r in REDES_PRIVADAS)


def ip_permitida(ip: str, permitir_loopback: bool = False) -> bool:
    """¿Puede este origen hablar con el listener LAN? Privadas siempre; loopback solo en pruebas."""
    if ip_privada(ip):
        return True
    if not permitir_loopback:
        return False
    try:
        return ipaddress.ip_address(ip) in LOOPBACK
    except ValueError:
        return False


@dataclass
class Adaptador:
    nombre: str
    descripcion: str
    tipo: int
    ips: list[str] = field(default_factory=list)
    con_puerta_enlace: bool = False
    metrica: int = 0
    indice: int = 0

    @property
    def es_wifi(self) -> bool:
        return self.tipo == IF_TIPO_WIFI

    @property
    def es_virtual(self) -> bool:
        texto = f'{self.nombre} {self.descripcion}'.lower()
        return self.tipo in (IF_TIPO_LOOPBACK, IF_TIPO_TUNEL) or any(p in texto for p in _PALABRAS_VIRTUAL)


def _rango(a: Adaptador) -> int:
    if a.es_virtual:
        return 5
    if a.es_wifi:
        return 0 if a.con_puerta_enlace else 1
    if a.con_puerta_enlace:
        return 2
    return 3 if a.tipo == IF_TIPO_ETHERNET else 4


def ordenar_direcciones(adaptadores: list[Adaptador]) -> list[str]:
    """IPv4 privadas sin repetir: Wi-Fi primero, luego ruta por defecto, Ethernet y virtuales al final."""
    vistas: list[str] = []
    for a in sorted(adaptadores, key=lambda x: (_rango(x), x.metrica, x.indice)):
        for ip in a.ips:
            if ip_privada(ip) and ip not in vistas:
                vistas.append(ip)
    return vistas


# ------------------------------------------------------------------ GetAdaptersAddresses (ctypes)
class _SockaddrIn(ctypes.Structure):
    _fields_ = [('sin_family', ctypes.c_short), ('sin_port', ctypes.c_ushort), ('sin_addr', ctypes.c_ubyte * 4),
                ('sin_zero', ctypes.c_char * 8)]


class _SocketAddress(ctypes.Structure):
    _fields_ = [('lpSockaddr', ctypes.c_void_p), ('iSockaddrLength', ctypes.c_int)]


class _Unicast(ctypes.Structure):
    pass


_Unicast._fields_ = [('Length', wintypes.ULONG), ('Flags', wintypes.DWORD), ('Next', ctypes.POINTER(_Unicast)),
                     ('Address', _SocketAddress)]


class _Gateway(ctypes.Structure):
    pass


_Gateway._fields_ = [('Length', wintypes.ULONG), ('Reserved', wintypes.DWORD), ('Next', ctypes.POINTER(_Gateway)),
                     ('Address', _SocketAddress)]


class _Adaptador(ctypes.Structure):
    """IP_ADAPTER_ADDRESSES_LH hasta Ipv4Metric (solo se lee; el resto de la estructura no se usa)."""


_Adaptador._fields_ = [
    ('Length', wintypes.ULONG), ('IfIndex', wintypes.DWORD), ('Next', ctypes.POINTER(_Adaptador)),
    ('AdapterName', ctypes.c_char_p), ('FirstUnicastAddress', ctypes.POINTER(_Unicast)),
    ('FirstAnycastAddress', ctypes.c_void_p), ('FirstMulticastAddress', ctypes.c_void_p),
    ('FirstDnsServerAddress', ctypes.c_void_p), ('DnsSuffix', ctypes.c_wchar_p), ('Description', ctypes.c_wchar_p),
    ('FriendlyName', ctypes.c_wchar_p), ('PhysicalAddress', ctypes.c_ubyte * 8), ('PhysicalAddressLength', wintypes.ULONG),
    ('Flags', wintypes.ULONG), ('Mtu', wintypes.ULONG), ('IfType', wintypes.ULONG), ('OperStatus', ctypes.c_int),
    ('Ipv6IfIndex', wintypes.ULONG), ('ZoneIndices', wintypes.ULONG * 16), ('FirstPrefix', ctypes.c_void_p),
    ('TransmitLinkSpeed', ctypes.c_ulonglong), ('ReceiveLinkSpeed', ctypes.c_ulonglong),
    ('FirstWinsServerAddress', ctypes.c_void_p), ('FirstGatewayAddress', ctypes.POINTER(_Gateway)),
    ('Ipv4Metric', wintypes.ULONG), ('Ipv6Metric', wintypes.ULONG)]

_AF_INET = 2
_GAA_FLAGS = 0x0002 | 0x0004 | 0x0008 | 0x0080        # sin anycast, multicast ni DNS; con puertas de enlace
_ERROR_BUFFER_OVERFLOW = 111


def _ipv4(sa: _SocketAddress) -> str | None:
    if not sa.lpSockaddr or sa.iSockaddrLength < ctypes.sizeof(_SockaddrIn):
        return None
    s = ctypes.cast(sa.lpSockaddr, ctypes.POINTER(_SockaddrIn)).contents
    if s.sin_family != _AF_INET:
        return None
    return '.'.join(str(b) for b in s.sin_addr)


def adaptadores() -> list[Adaptador]:
    """Adaptadores IPv4 encendidos con sus direcciones. [] si la API falla."""
    try:
        iphlp = ctypes.WinDLL('iphlpapi')
    except OSError:
        return []
    fn = iphlp.GetAdaptersAddresses
    fn.argtypes = [wintypes.ULONG, wintypes.ULONG, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(wintypes.ULONG)]
    fn.restype = wintypes.ULONG
    tam = wintypes.ULONG(16 * 1024)
    buf = None
    for _ in range(4):
        buf = ctypes.create_string_buffer(tam.value)
        r = fn(_AF_INET, _GAA_FLAGS, None, buf, ctypes.byref(tam))
        if r == 0:
            break
        if r != _ERROR_BUFFER_OVERFLOW:
            _log.debug('GetAdaptersAddresses devolvió %d', r)
            return []
    else:
        return []
    salida: list[Adaptador] = []
    p = ctypes.cast(buf, ctypes.POINTER(_Adaptador))
    while p:
        a = p.contents
        if a.OperStatus == IF_OPER_ARRIBA and a.IfType != IF_TIPO_LOOPBACK:
            ips: list[str] = []
            u = a.FirstUnicastAddress
            while u:
                ip = _ipv4(u.contents.Address)
                if ip:
                    ips.append(ip)
                u = u.contents.Next
            g = a.FirstGatewayAddress
            con_gw = False
            while g:
                gw = _ipv4(g.contents.Address)
                if gw and gw != '0.0.0.0':
                    con_gw = True
                g = g.contents.Next
            salida.append(Adaptador(nombre=a.FriendlyName or '', descripcion=a.Description or '', tipo=int(a.IfType),
                                    ips=ips, con_puerta_enlace=con_gw, metrica=int(a.Ipv4Metric),
                                    indice=int(a.IfIndex)))
        p = a.Next
    return salida


def _respaldo() -> list[str]:
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        return []
    vistas: list[str] = []
    for *_, sa in infos:
        ip = sa[0]
        if ip_privada(ip) and ip not in vistas:
            vistas.append(ip)
    return vistas


def direcciones_privadas() -> list[str]:
    """IPv4 privadas de la PC, Wi-Fi primero (LanEstado.direcciones, EmparejarResponse.direcciones y el QR)."""
    try:
        lista = ordenar_direcciones(adaptadores())
    except (OSError, ValueError, ctypes.ArgumentError):
        lista = []
    return lista or _respaldo()
