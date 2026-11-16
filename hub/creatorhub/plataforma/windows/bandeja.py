"""Ícono de la bandeja (04 §A.6): WinForms `NotifyIcon` por pythonnet, creado en el hilo de la interfaz.

Texto «Corte». Menú: «Abrir Corte» · «Sincronizar ahora» · separador · «Salir». Clic (o doble clic) → abre la ventana.
Los globos (`ShowBalloonTip`) funcionan también con la ventana oculta; el clic en un globo llama `al_clic_globo(ruta)`
(la ventana publica `ventana.mostrar_ruta`). Las acciones del menú corren en un hilo aparte para no bloquear la interfaz.

`crear`, `globo` y `quitar` deben llamarse EN EL HILO DE LA INTERFAZ (la ventana lo garantiza). La fábrica de WinForms
es inyectable para probar sin pythonnet.
"""
from __future__ import annotations

import logging
import os
import threading
from types import SimpleNamespace
from typing import Any, Callable

_log = logging.getLogger('creatorhub.plataforma.bandeja')

TOOLTIP = 'Corte'
TEXTO_ABRIR = 'Abrir Corte'
TEXTO_SINCRONIZAR = 'Sincronizar ahora'
TEXTO_SALIR = 'Salir'
DURACION_GLOBO_MS = 8000


def fabrica_winforms() -> SimpleNamespace:
    import clr  # noqa: F401  (pythonnet; ya lo cargó pywebview)
    from System.Drawing import Icon, SystemIcons
    from System.Windows.Forms import ContextMenuStrip, MouseButtons, NotifyIcon, ToolStripSeparator, ToolTipIcon
    return SimpleNamespace(NotifyIcon=NotifyIcon, ContextMenuStrip=ContextMenuStrip, ToolStripSeparator=ToolStripSeparator,
                           Icon=Icon, SystemIcons=SystemIcons, ToolTipIcon=ToolTipIcon, MouseButtons=MouseButtons)


def _en_hilo(fn: Callable[..., Any], *args: Any) -> None:
    def correr() -> None:
        try:
            fn(*args)
        except Exception:  # noqa: BLE001
            _log.exception('Error en una acción de la bandeja')
    threading.Thread(target=correr, name='bandeja-accion', daemon=True).start()


class Bandeja:
    def __init__(self, ruta_icono: str | None, al_abrir: Callable[[], None], al_sincronizar: Callable[[], None],
                 al_salir: Callable[[], None], al_clic_globo: Callable[[str], None],
                 fabrica: Callable[[], Any] = fabrica_winforms, icono_respaldo: Any = None) -> None:
        self.ruta_icono = ruta_icono
        self._al_abrir = al_abrir
        self._al_sincronizar = al_sincronizar
        self._al_salir = al_salir
        self._al_clic_globo = al_clic_globo
        self._fabrica = fabrica
        self._icono_respaldo = icono_respaldo
        self._wf: Any = None
        self.icono: Any = None
        self.menu: Any = None
        self.ruta_globo = '#/'
        self.globos: int = 0

    # ------------------------------------------------------------------ hilo de la interfaz
    def crear(self) -> None:
        wf = self._wf = self._fabrica()
        icono = wf.NotifyIcon()
        if self.ruta_icono and os.path.isfile(self.ruta_icono):
            icono.Icon = wf.Icon(self.ruta_icono)
        elif self._icono_respaldo is not None:
            icono.Icon = self._icono_respaldo
        else:
            icono.Icon = wf.SystemIcons.Application
        icono.Text = TOOLTIP
        menu = wf.ContextMenuStrip()
        abrir = menu.Items.Add(TEXTO_ABRIR)
        abrir.Click += lambda _s, _e: _en_hilo(self._al_abrir)
        sincronizar = menu.Items.Add(TEXTO_SINCRONIZAR)
        sincronizar.Click += lambda _s, _e: _en_hilo(self._al_sincronizar)
        menu.Items.Add(wf.ToolStripSeparator())
        salir = menu.Items.Add(TEXTO_SALIR)
        salir.Click += lambda _s, _e: _en_hilo(self._al_salir)
        icono.ContextMenuStrip = menu
        icono.MouseClick += self._al_clic
        icono.BalloonTipClicked += lambda _s, _e: _en_hilo(self._al_clic_globo, self.ruta_globo)
        icono.Visible = True
        self.icono, self.menu = icono, menu
        _log.info('Ícono de la bandeja creado')

    def _al_clic(self, _remitente: Any, args: Any) -> None:
        try:
            izquierdo = args.Button == self._wf.MouseButtons.Left
        except Exception:  # noqa: BLE001
            izquierdo = True
        if izquierdo:
            _en_hilo(self._al_abrir)

    def globo(self, titulo: str, texto: str, ruta: str) -> None:
        if self.icono is None:
            _log.warning('Globo pedido antes de crear la bandeja: se omite')
            return
        self.ruta_globo = ruta
        self.icono.ShowBalloonTip(DURACION_GLOBO_MS, titulo, texto, getattr(self._wf.ToolTipIcon, 'None'))
        self.globos += 1

    def quitar(self) -> None:
        icono, self.icono = self.icono, None
        if icono is not None:
            try:
                icono.Visible = False
                icono.Dispose()
            except Exception:  # noqa: BLE001
                _log.debug('No se pudo quitar el ícono de la bandeja', exc_info=True)
