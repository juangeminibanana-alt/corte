"""Transporte FALSO de la Display API para el modo demo (rev. 5). Nunca usa la red.

Perfil y videos SINTÉTICOS de la identidad de demo (USUARIO_DEMO de demo/transporte.py), coherentes con las ventas de `demo/sinteticos.py`: los 90 videos con
venta de la demo (sus content_id) más 30 videos públicos sin ventas. Cada video se publicó 1–3 días antes de su primera
venta; las vistas crecen con los pedidos que trajo y con los días que lleva publicado (curva 1 − e^(−días/20)), así que
cada día la sync guarda cifras un poco mayores (la tendencia se ve en la demo). Generador aleatorio PROPIO (semilla
fija): no mueve ninguna cifra documentada de la demo. Portadas en un host de demostración del CDN de la lista blanca
(`p16-corte-demo.tiktokcdn.com`); el descargador demo las dibuja.

Rutas: POST /v2/oauth/token/ (code o refresh: tokens falsos nuevos, el refresh_token ROTA) · POST /v2/oauth/revoke/ ·
GET /v2/user/info/ · POST /v2/video/list/ (más recientes primero, cursor = create_time del último en ms, has_more).
"""
from __future__ import annotations

import collections
import datetime as dt
import itertools
import json
import math
import random
import threading
import urllib.parse
from typing import Any, Mapping

from ..comun import TZ_MX
from ..demo.transporte import USUARIO_DEMO  # el literal de la identidad demo vive solo allí (guardia_exe, BUILD §6.3)
from ..interfaces import Json, Reloj
from .boveda import ACCESO_DEMO, OPEN_ID_DEMO, SCOPES_DEMO

SEMILLA = 20261115
VIDEOS_SIN_VENTA = 30
HOST_PORTADAS = 'p16-corte-demo.tiktokcdn.com'
SEGUIDORES_BASE = 48200


def url_portada(video_id: str, ahora: int) -> str:
    return f'https://{HOST_PORTADAS}/obj/corte-demo/portada/{video_id}.jpeg?x-expires={ahora + 6 * 3600}&x-signature=demo'


class TransporteDisplayDemo:
    """Implementa `interfaces.Transporte` para la Display API de demostración."""

    def __init__(self, reloj: Reloj) -> None:
        self.reloj = reloj
        self._candado = threading.Lock()
        self._base: list[dict[str, Any]] | None = None
        self._n = itertools.count(1)
        self.llamadas: collections.Counter = collections.Counter()

    # ------------------------------------------------------------------ datos
    def _videos_base(self) -> list[dict[str, Any]]:
        """[{id, creado_at, pedidos, titulo, duracion, factor}] (no depende del día: sí de la fecha de cada venta)."""
        with self._candado:
            if self._base is not None:
                return self._base
            from ..demo import sinteticos
            ahora = int(self.reloj.ahora())
            cat = sinteticos.catalogo()
            primera: dict[str, int] = {}
            pedidos: collections.Counter = collections.Counter()
            productos: dict[str, str] = {}
            for o in sinteticos.generar(ahora).ordenes:
                for s in o.get('skus') or []:
                    cid = s.get('content_id')
                    if s.get('content_type') == 'VIDEO' and cid:
                        primera[cid] = min(primera.get(cid, o['create_time']), o['create_time'])
                        pedidos[cid] += 1
                        productos.setdefault(cid, s.get('product_name') or '')
            rng = random.Random(SEMILLA)
            base = []
            for cid in cat.videos:
                inicio = primera.get(cid, ahora - 200 * 86400)
                base.append({'id': cid, 'creado_at': inicio - rng.randrange(86400, 3 * 86400),
                             'pedidos': pedidos.get(cid, 0), 'titulo': productos.get(cid) or 'Mi favorito de la semana',
                             'duracion': 12 + rng.randrange(80), 'factor': rng.uniform(150, 900),
                             'extra': rng.randrange(800, 6000), 'tasa_like': rng.uniform(0.03, 0.09)})
            for _ in range(VIDEOS_SIN_VENTA):
                vid = '7' + ''.join(str(rng.randrange(10)) for _ in range(18))
                base.append({'id': vid, 'creado_at': ahora - rng.randrange(2 * 86400, 300 * 86400), 'pedidos': 0,
                             'titulo': rng.choice(('Rutina de mañana', 'Lo que me puse esta semana', 'Ordenando la casa',
                                                   'Probando cosas virales', 'Preguntas y respuestas')),
                             'duracion': 10 + rng.randrange(120), 'factor': 0.0, 'extra': rng.randrange(300, 9000),
                             'tasa_like': rng.uniform(0.02, 0.07)})
            base.sort(key=lambda v: (-v['creado_at'], v['id']))
            self._base = base
            return base

    def _video(self, b: Mapping[str, Any], ahora: int) -> dict[str, Any]:
        dias = max(0.0, (ahora - b['creado_at']) / 86400)
        madurez = 1 - math.exp(-dias / 20)
        vistas = int((b['pedidos'] * b['factor'] + b['extra']) * (0.35 + 0.65 * madurez))
        likes = int(vistas * b['tasa_like'])
        nombre = str(b['titulo'])
        return {'id': b['id'], 'create_time': int(b['creado_at']), 'cover_image_url': url_portada(b['id'], ahora),
                'share_url': f'https://www.tiktok.com/@{USUARIO_DEMO}/video/{b["id"]}', 'title': nombre,
                'video_description': f'{nombre} #tiktokshop #demo', 'duration': int(b['duracion']),
                'embed_link': f'https://www.tiktok.com/player/v1/{b["id"]}', 'view_count': vistas, 'like_count': likes,
                'comment_count': int(likes * 0.03), 'share_count': int(likes * 0.05)}

    def _usuario(self, ahora: int) -> dict[str, Any]:
        base = self._videos_base()
        dias = (dt.datetime.fromtimestamp(ahora, TZ_MX).date() - dt.date(2026, 1, 1)).days
        likes = sum(self._video(b, ahora)['like_count'] for b in base)
        return {'open_id': OPEN_ID_DEMO, 'union_id': 'UNION_ID_DISPLAY_DEMO', 'avatar_url': None,
                'display_name': 'Creador Demo', 'bio_description': 'Reseñas honestas de ropa y hogar · demo de Corte',
                'profile_deep_link': f'https://www.tiktok.com/@{USUARIO_DEMO}', 'is_verified': False,
                'username': USUARIO_DEMO, 'follower_count': SEGUIDORES_BASE + 60 * max(0, dias),
                'following_count': 312, 'likes_count': int(likes * 1.3), 'video_count': len(base)}

    # ------------------------------------------------------------------ Transporte
    @staticmethod
    def _ok(data: Json) -> tuple[int, Json]:
        return 200, {'data': data, 'error': {'code': 'ok', 'message': '', 'log_id': 'demo'}}

    def manejar(self, metodo: str, url: str, cabeceras: Mapping[str, str], cuerpo: bytes | None) -> tuple[int, Json | None]:
        u = urllib.parse.urlsplit(url)
        ruta = u.path
        self.llamadas[ruta] += 1
        ahora = int(self.reloj.ahora())
        if ruta == '/v2/oauth/token/':
            n = next(self._n)
            return 200, {'access_token': f'{ACCESO_DEMO}-{n}', 'refresh_token': f'rft.demo-display-{n}',
                         'expires_in': 7200, 'refresh_expires_in': 180 * 86400, 'open_id': OPEN_ID_DEMO,
                         'scope': ','.join(SCOPES_DEMO), 'token_type': 'Bearer'}
        if ruta == '/v2/oauth/revoke/':
            return 200, {}
        auth = next((v for k, v in cabeceras.items() if k.lower() == 'authorization'), '')
        if not auth.startswith('Bearer act.demo-display'):
            return 401, {'data': {}, 'error': {'code': 'access_token_invalid', 'message': '', 'log_id': 'demo'}}
        if ruta == '/v2/user/info/' and metodo == 'GET':
            campos = (urllib.parse.parse_qs(u.query).get('fields') or [''])[0].split(',')
            user = self._usuario(ahora)
            return self._ok({'user': {k: v for k, v in user.items() if k in campos}})
        if ruta == '/v2/video/list/' and metodo == 'POST':
            try:
                pedido = json.loads((cuerpo or b'{}').decode('utf-8'))
            except ValueError:
                pedido = {}
            maximo = max(1, min(20, int(pedido.get('max_count') or 20)))
            cursor = pedido.get('cursor')
            lista = [b for b in self._videos_base() if b['creado_at'] <= ahora
                     and (cursor is None or b['creado_at'] * 1000 < int(cursor))]
            pagina = lista[:maximo]
            videos = [self._video(b, ahora) for b in pagina]
            siguiente = pagina[-1]['creado_at'] * 1000 if pagina else (cursor or 0)
            return self._ok({'videos': videos, 'cursor': siguiente, 'has_more': len(lista) > maximo})
        return 404, {'data': {}, 'error': {'code': 'invalid_params', 'message': '', 'log_id': 'demo'}}


__all__ = ['TransporteDisplayDemo', 'url_portada', 'HOST_PORTADAS', 'VIDEOS_SIN_VENTA']
