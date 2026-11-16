"""Adaptadores de servidor: bóveda portable y OAuth HTTPS; sin servicios de Windows."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .boveda import BovedaDpapi
from .interfaces import Rutas
from .tiktok_dev.boveda import BovedaDisplay


class _CifradoPortable:
    """Conserva concurrencia, revisiones e idempotencia de la bóveda existente.

    La llave maestra vive fuera del volumen. Una llave incorrecta o un archivo
    dañado detienen el arranque: nunca se reemplazan credenciales por un vacío.
    """

    def __init__(self, ruta: str, clave: str, proposito: str) -> None:
        if len(clave) < 32:
            raise ValueError('CORTE_ENCRYPTION_KEY necesita al menos 32 caracteres aleatorios.')
        self._aad = ('Corte/nube/' + proposito + '/v1').encode('ascii')
        self._aes = AESGCM(HKDF(algorithm=hashes.SHA256(), length=32,
                               salt=None, info=self._aad).derive(clave.encode('utf-8')))
        super().__init__(ruta)

    def _leer_sobre(self, ruta: str) -> dict[str, Any]:
        try:
            raw = Path(ruta).read_bytes()
            if len(raw) > 1024 * 1024:
                raise ValueError('size')
            sobre = json.loads(raw)
            if sobre['v'] != 1:
                raise ValueError('version')
            datos = json.loads(self._aes.decrypt(base64.b64decode(sobre['nonce'], validate=True),
                                                  base64.b64decode(sobre['blob'], validate=True), self._aad))
            if not isinstance(datos, dict) or not isinstance(datos.get('generacion'), int):
                raise ValueError('payload')
            return datos
        except FileNotFoundError:
            raise
        except Exception:
            raise RuntimeError('No se puede descifrar la bóveda. Conserva los archivos y revisa la llave maestra.') from None

    def _cargar(self) -> dict[str, Any]:
        presentes: list[tuple[str, dict[str, Any]]] = []
        for ruta in (self.ruta, self.ruta + '.nuevo'):
            try:
                presentes.append((ruta, self._leer_sobre(ruta)))
            except FileNotFoundError:
                pass
        if not presentes:
            return {}
        ruta, datos = max(presentes, key=lambda item: item[1]['generacion'])
        if ruta != self.ruta:
            os.replace(ruta, self.ruta)
        return datos

    def _persistir(self, datos: Mapping[str, Any]) -> None:
        Path(self.ruta).parent.mkdir(parents=True, exist_ok=True)
        nonce = os.urandom(12)
        plano = json.dumps(dict(datos), ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        sobre = json.dumps({'v': 1, 'nonce': base64.b64encode(nonce).decode('ascii'),
                            'blob': base64.b64encode(self._aes.encrypt(nonce, plano, self._aad)).decode('ascii')})
        nuevo = self.ruta + '.nuevo'
        descriptor = os.open(nuevo, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(descriptor, 'w', encoding='ascii') as archivo:
                archivo.write(sobre)
                archivo.flush()
                os.fsync(archivo.fileno())
            os.replace(nuevo, self.ruta)
        except BaseException:
            Path(nuevo).unlink(missing_ok=True)
            raise


class BovedaNube(_CifradoPortable, BovedaDpapi):
    pass


class BovedaDisplayNube(_CifradoPortable, BovedaDisplay):
    pass


def crear_boveda_nube(rutas: Rutas, display: bool = False) -> BovedaDpapi:
    nombre = 'tiktok_display.aesgcm' if display else 'credenciales.aesgcm'
    clase = BovedaDisplayNube if display else BovedaNube
    return clase(os.path.join(rutas.secretos, nombre), os.environ.get('CORTE_ENCRYPTION_KEY', ''),
                 'display' if display else 'shop')


def configurar_auth_nube(hub: Any) -> None:
    origen = os.environ['CORTE_PUBLIC_URL'].rstrip('/')
    retorno = os.environ.get('CORTE_SHOP_CALLBACK_URL', origen + '/oauth/shop')
    u = urlsplit(retorno)
    local_http = (os.environ.get('CORTE_ALLOW_HTTP') == '1' and u.scheme == 'http'
                  and u.hostname in ('localhost', '127.0.0.1', '::1'))
    if (not u.hostname or (u.scheme != 'https' and not local_http) or u.username or u.password
            or (not local_http and u.port not in (None, 443)) or u.query or u.fragment):
        raise ValueError('CORTE_SHOP_CALLBACK_URL debe ser una URL HTTPS sin parámetros.')
    hub.auth.nube = True
    hub.auth.host_retorno = u.hostname
    hub.auth.ruta_retorno = u.path or '/'
    hub.auth.esquema_retorno = u.scheme
    hub.auth.puerto_retorno = u.port or (443 if u.scheme == 'https' else 80)
    hub.auth.portapapeles_sistema = None
    hub.display.redirect_uri = origen + '/oauth/tiktok'

