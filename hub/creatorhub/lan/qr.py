"""PNG del QR de emparejamiento (EmparejarResponse.qr_png; BUILD §6.1, C3; 04 §C.4).

- `qrcode` + `qrcode.image.pure.PyPNGImage` (pypng), corrección M. **Nunca PIL** en `lan/`.
- Import PEREZOSO: nada de `qrcode` se carga hasta el primer QR (no pesa en `t_hub_listo_ms`).
- Con Pillow instalado, `import qrcode` 8.2 carga PIL de rebote (`qrcode.image.base` importa
  `qrcode.image.styles.moduledrawers`, cuyo `__init__` intenta `from .pil import …` dentro de un `try/except
  ImportError`). Por eso el primer import se hace con un buscador en `sys.meta_path` que, SOLO en el hilo que importa
  y SOLO durante ese import, responde ModuleNotFoundError a `PIL`/`PIL.*`: qrcode cae en su rama sin PIL y PIL nunca
  entra a `sys.modules` por culpa de este módulo. Los demás hilos (p. ej. los trabajadores de imágenes) no se enteran.
"""
from __future__ import annotations

import base64
import importlib.abc
import io
import sys
import threading
from typing import Any

CAJA_PX = 8          # ~61 módulos (versión ~9 + borde 4) × 8 = 488 px: nítido a 240 px CSS con pantallas 2×
BORDE = 4
_candado = threading.Lock()
_cargado: tuple[Any, Any, Any] | None = None


class _SinPil(importlib.abc.MetaPathFinder):
    def __init__(self, hilo: int) -> None:
        self.hilo = hilo

    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> None:
        if (fullname == 'PIL' or fullname.startswith('PIL.')) and threading.get_ident() == self.hilo:
            raise ModuleNotFoundError(f'No module named {fullname!r} (lan/qr.py no usa PIL)', name=fullname)
        return None


def _qrcode() -> tuple[Any, Any, Any]:
    """-> (qrcode.main.QRCode, qrcode.constants, PyPNGImage), importados una vez sin PIL."""
    global _cargado
    with _candado:
        if _cargado is None:
            bloqueo = _SinPil(threading.get_ident())
            sys.meta_path.insert(0, bloqueo)
            try:
                from qrcode import constants
                from qrcode.image.pure import PyPNGImage
                from qrcode.main import QRCode
            finally:
                sys.meta_path.remove(bloqueo)
            _cargado = (QRCode, constants, PyPNGImage)
        return _cargado


def matriz(texto: str) -> list[list[bool]]:
    """Módulos del QR (True = oscuro), sin borde. Lo usan las pruebas para comparar con el PNG."""
    QRCode, constants, PyPNGImage = _qrcode()
    qr = QRCode(error_correction=constants.ERROR_CORRECT_M, border=BORDE, image_factory=PyPNGImage)
    qr.add_data(texto)
    qr.make(fit=True)
    return [[bool(m) for m in fila] for fila in qr.modules]


def png(texto: str, caja_px: int = CAJA_PX, borde: int = BORDE) -> bytes:
    """PNG en escala de grises de 1 bit (módulos negros sobre blanco) con el texto del QR."""
    QRCode, constants, PyPNGImage = _qrcode()
    qr = QRCode(error_correction=constants.ERROR_CORRECT_M, box_size=caja_px, border=borde, image_factory=PyPNGImage)
    qr.add_data(texto)
    qr.make(fit=True)
    imagen = qr.make_image(image_factory=PyPNGImage)
    salida = io.BytesIO()
    imagen.save(salida)
    return salida.getvalue()


def data_uri(texto: str) -> str:
    """'data:image/png;base64,…' (EmparejarResponse.qr_png)."""
    return 'data:image/png;base64,' + base64.b64encode(png(texto)).decode('ascii')
