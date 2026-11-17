"""Ventas pagadas por fecha de compra y calendario de pago declarado por el usuario.

La API Creator no aporta saldo de retiro, período incluido en un depósito ni fecha
de liquidación. El miércoles mostrado es un calendario, nunca un abono confirmado.
No cambia las métricas históricas del contrato anterior.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from typing import Any

from .. import comun

_PAGADOS = frozenset({'To-SETTLE', 'SETTLED'})


def _netas(fila: dict[str, Any]) -> int:
    return max(0, fila['cantidad'] - max(fila['reembolsadas'], fila['devueltas']))


def _monto(filas: list[dict[str, Any]], campo: str, *, venta: bool = False) -> int | None:
    """La ausencia del monto/moneda o una orden incompleta no se convierte en cero."""
    if any(f['moneda'] != 'MXN' or f[campo] is None or f['huella'] == 'incompleta' for f in filas):
        return None
    return sum(f[campo] * (_netas(f) if venta else 1) for f in filas)


def _resumen(filas: list[dict[str, Any]]) -> dict[str, Any]:
    pagadas = [f for f in filas if f['estado'] in _PAGADOS and _netas(f) > 0]
    impagas = [f for f in filas if f['estado'] == 'AWAITING PAYMENT' and _netas(f) > 0]
    return {
        'pedidos_validos': len({f['order_id'] for f in pagadas}),
        'pedidos_pendientes_pago': len({f['order_id'] for f in impagas}),
        'unidades': sum(_netas(f) for f in pagadas),
        'ventas_centavos': _monto(pagadas, 'precio_centavos', venta=True),
        'comision_estimada_centavos': _monto(pagadas, 'com_estimada_centavos'),
        'ultima_venta_at': max((f['creada_at'] for f in pagadas), default=None),
        'datos_parciales': any(f['huella'] == 'incompleta' for f in pagadas),
    }


def resumen_actualidad(conn: sqlite3.Connection, ahora: int) -> dict[str, Any]:
    """Se ejecuta en la misma transacción de lectura del dashboard/snapshot."""
    hoy = comun.ts_local(ahora).date()
    lunes = hoy - dt.timedelta(days=hoy.weekday())
    domingo = lunes + dt.timedelta(days=6)
    miercoles = hoy + dt.timedelta(days=(2 - hoy.weekday()) % 7)
    filas = [dict(f) for f in conn.execute(
        'SELECT o.order_id,o.creada_at,o.estado,o.huella,l.precio_centavos,l.moneda,l.cantidad,'
        'l.reembolsadas,l.devueltas,l.com_estimada_centavos FROM ordenes o '
        'JOIN orden_lineas l USING(order_id) WHERE o.creada_at<=? AND NOT EXISTS '
        '(SELECT 1 FROM muestras m WHERE m.main_order_id=o.order_id)', (ahora,))]
    inicio_hoy = comun.epoch_de_fecha_local(hoy.isoformat(), hora=0)
    inicio_semana = comun.epoch_de_fecha_local(lunes.isoformat(), hora=0)
    por_liquidar = [f for f in filas if f['estado'] == 'To-SETTLE' and _netas(f) > 0]
    retenidas = [f for f in filas if f['estado'] == 'FROZEN' and _netas(f) > 0]
    sin_pago = [f for f in filas if f['estado'] == 'AWAITING PAYMENT' and _netas(f) > 0]
    semana = _resumen([f for f in filas if f['creada_at'] >= inicio_semana])
    semana['comision_generada_estimada_centavos'] = semana['comision_estimada_centavos']
    return {
        'zona_horaria': 'America/Mexico_City', 'moneda': 'MXN', 'generado_at': ahora,
        'hoy': {'fecha': hoy.isoformat(), **_resumen([f for f in filas if f['creada_at'] >= inicio_hoy])},
        'semana': {'desde': lunes.isoformat(), 'hasta': domingo.isoformat(), **semana},
        'pendiente': {
            'comision_por_liquidar_centavos': _monto(por_liquidar, 'com_estimada_centavos'),
            'comision_retenida_centavos': _monto(retenidas, 'com_estimada_centavos'),
            'comision_pedidos_sin_pagar_centavos': _monto(sin_pago, 'com_estimada_centavos'),
        },
        'pago_semana': {
            'estado': 'no_disponible', 'monto_centavos': None, 'fecha_prevista': None,
            'dia_pago': 3, 'horario': 'madrugada', 'fecha_programada': miercoles.isoformat(),
            'origen_calendario': 'usuario',
            'motivo': ('El calendario indicado es cada miércoles. TikTok no informa en esta conexión '
                       'el saldo disponible para retiro ni qué comisiones incluirá el próximo depósito.'),
        },
    }
