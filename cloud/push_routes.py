"""Native-only, owner/creator/device scoped sale notification endpoints."""
from __future__ import annotations

import hmac
import re
from typing import Any, Callable

from flask import g, jsonify, request

from creatorhub.errores import ErrorDominio


def install_push_routes(app: Any, push: Any, hub: Any, native: Any,
                        scopes: Callable[..., dict[str, str]]) -> None:
    def invoke(action: str) -> Any:
        try:
            actor = getattr(g, 'native_actor', None)
            if not isinstance(actor, dict):
                raise ErrorDominio('sesion_nativa_requerida', 'Activa los avisos desde la aplicación de Corte.', http=401)
            if push is None or native is None:
                raise ErrorDominio('no_disponible', 'Los avisos de ventas requieren Corte Cloud con Google.', http=409)
            expected = request.headers.get('X-Corte-Cache-Scope')
            if not isinstance(expected, str) or re.fullmatch('[a-f0-9]{64}', expected) is None:
                raise ErrorDominio('cuenta_cambio_sin_aplicar', 'Actualiza Corte antes de configurar los avisos.', http=409)
            uid, device = actor['claims']['uid'], actor['device_id']
            # Same lock as creator/auth mutations; keep registration attached to this exact creator.
            with hub._candado_mutacion:
                stored = hub.boveda.leer()
                creator = stored.get('open_id') if isinstance(stored, dict) else None
                current = scopes(actor['claims'], creator).get('cache_scope')
                if current is None or not hmac.compare_digest(current, expected):
                    raise ErrorDominio('cuenta_cambio_sin_aplicar', 'La cuenta cambió. Actualiza Corte.', http=409)
                if action == 'register':
                    body = request.get_json(silent=True)
                    device_info = next((d for d in native.devices(uid) if d['device_id'] == device), None)
                    if not isinstance(body, dict) or device_info is None or body.get('platform') != device_info['platform']:
                        raise ErrorDominio('parametros_invalidos', 'El dispositivo del aviso no es válido.', http=422)
                    result = push.register(uid, current, device, body)
                elif action == 'disable':
                    if request.get_json(silent=True) not in (None, {}):
                        raise ErrorDominio('parametros_invalidos', 'La solicitud del aviso no es válida.', http=422)
                    push.disable(uid, device, current)
                    result = push.status(uid, current, device)
                elif action == 'events':
                    if set(request.args) - {'after'} or len(request.args.getlist('after')) > 1:
                        raise ErrorDominio('parametros_invalidos', 'El cursor del aviso no es válido.', http=422)
                    result = push.events(uid, current, device, request.args.get('after', '0'))
                elif action == 'ack':
                    result = push.ack(uid, current, device, request.get_json(silent=True))
                elif action == 'test':
                    result = push.test_notification(uid, current, device, request.get_json(silent=True))
                else:
                    result = push.status(uid, current, device)
            return (jsonify(result), 202) if action == 'test' else jsonify(result)
        except ErrorDominio as error:
            response = jsonify(error.a_respuesta())
            if error.reintentar_en_s is not None:
                response.headers['Retry-After'] = str(error.reintentar_en_s)
            return response, error.http

    app.add_url_rule('/api/push/register', 'push_register', lambda: invoke('register'), methods=['POST'])
    app.add_url_rule('/api/push/register', 'push_disable', lambda: invoke('disable'), methods=['DELETE'])
    app.add_url_rule('/api/push/status', 'push_status', lambda: invoke('status'), methods=['GET'])
    app.add_url_rule('/api/push/events', 'push_events', lambda: invoke('events'), methods=['GET'])
    app.add_url_rule('/api/push/ack', 'push_ack', lambda: invoke('ack'), methods=['POST'])
    app.add_url_rule('/api/push/test', 'push_test', lambda: invoke('test'), methods=['POST'])
