"""Modo demo del hub (hub-sync; BUILD_SPEC §6.2, §6.3.1, §6.3.4; 03 §9.2 y §9.4). Exporta las fábricas:

- `crear_transporte_demo(fuente, reloj)`: 'sinteticos' = datos inventados de demo/sinteticos.py (lo único que viaja en
  el exe; cifras documentadas en su encabezado); 'fixtures_reales' = FakeTikTok sobre research/datos-reales, SOLO en
  desarrollo (con `sys.frozen` lanza ValueError).
- `crear_descargador_demo(fuente)`: `url -> bytes` sin red (originales de ui/fixtures/img o marcadores con Pillow).
"""
from __future__ import annotations

import sys

from ..interfaces import Descargador, FuenteDemo, Reloj, Transporte
from . import sinteticos
from .descargador import crear_descargador
from .transporte import TransporteApiFalsa, TransporteFixtures, perfil_demo

FUENTES: tuple[str, ...] = ('sinteticos', 'fixtures_reales')


def _validar(fuente: str) -> None:
    if fuente not in FUENTES:
        raise ValueError(f'fuente de demo desconocida: {fuente!r}')
    if fuente == 'fixtures_reales' and getattr(sys, 'frozen', False):
        raise ValueError("La fuente 'fixtures_reales' solo existe en desarrollo (el exe solo trae datos sintéticos)")


def crear_transporte_demo(fuente: FuenteDemo, reloj: Reloj) -> Transporte:
    _validar(fuente)
    if fuente == 'fixtures_reales':
        return TransporteFixtures(reloj)
    return TransporteApiFalsa(sinteticos.generar(reloj.ahora()), reloj)


def crear_descargador_demo(fuente: FuenteDemo) -> Descargador:
    _validar(fuente)
    return crear_descargador(fuente)


__all__ = ['crear_transporte_demo', 'crear_descargador_demo', 'FUENTES', 'perfil_demo', 'TransporteApiFalsa',
           'TransporteFixtures']
