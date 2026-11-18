"""Datos SINTÉTICOS del modo demo (03 §9.4; BUILD_SPEC §6.3.4 y §11.4 b). Es lo único que viaja dentro del exe/APK
para demostraciones: tiendas, productos, videos e ids son INVENTADOS (no son de ninguna cuenta real).

Forma estadística de una cuenta típica: una mezcla de estados de solicitud variada (la mayoría vencidas o sin envío),
pedidos con pico 1 a 4 meses antes de hoy, una tienda dominante que concentra la mayoría de los pedidos, una parte de
reembolsos y pedidos con la misma SKU repetida en varias líneas. Todas las fechas son RELATIVAS al día de hoy
(hora de México): las cifras de abajo no cambian con la fecha en que se abra la demo.

CIFRAS DOCUMENTADAS (después de una sincronización completa; periodo «Todo»). Las muestra `CreatorHub.exe --demo` y las
reproduce hub/pruebas/test_sync_demo.py sincronizando de punta a punta (sincronizador + almacén + estas respuestas):

  Muestras
    Solicitudes de muestra ......................... 108
    Pendientes («Te faltan 34 videos») ............. 34   (vencidas 30 · por vencer 3 · pausada 1)
    Tiendas con pendientes ......................... 25
    Recibidas ...................................... 44   (de 27 tiendas)
    Entregadas 6 · Exentas 4 · En camino 1 · Esperando aprobación 3 · Sin envío 60 · Pedido de muestra cancelado 0
    Deuda de las 30 vencidas ....................... pendiente 28 · video no vinculado 1 · producto no disponible 1
  Ventas (v_lineas, periodo «Todo»)
    Pedidos ........................................ 2,501  (reembolsados 652)
    Líneas ......................................... 2,692
    Unidades vendidas (válidas) .................... 2,145
    Ventas (válidas) ............................... $833,805.00    (83380500 centavos; en KPI «$833,805»)
    Comisión total ................................. $96,561.05     (9656105 centavos; en KPI «$96,561»)
      = liquidada $86,014.01 + por liquidar $8,188.64 + retenida $2,358.40
    Tiendas con venta 31 · productos con venta 50 · videos con venta 90
    Tienda dominante (Moda Aurora MX) .............. 1,877 pedidos (75 % de 2,501)

Toda muestra sale de un producto en colaboración abierta (lo normal en la API): las 108 traen título, precio,
foto y el nombre de su tienda (ninguna tienda «Tienda …1234» ni producto sin nombre en la demo).

Definiciones (las mismas vistas que usa la analítica): pendiente = v_muestras.pendiente; recibidas = v_muestras.recibida;
pedidos = COUNT(DISTINCT order_id) de v_lineas; válidas = SETTLED, To-SETTLE o AWAITING PAYMENT; comisión total =
Σ comision_centavos (real si SETTLED, estimada si To-SETTLE/AWAITING PAYMENT/FROZEN).

Rev. 4 (ficha completa de producto; `_ficha_completa`, con su PROPIO generador aleatorio para no mover ninguna de las
cifras de arriba): galería de 5 a 9 fotos, inventario y precio con descuento de la plataforma en la vitrina;
elegibilidad de muestra con SKU de color/talla; planes dirigidos en tiendas con shop_id; origen de cada venta; una
solicitud que solo se conoce por su cumplimiento (su SKU sale del detalle); y la historia de la «comisión real»: dos
productos de Moda Aurora MX pagan en tus ventas la tasa de su plan dirigido (con campaña), 4 puntos más que su plan
abierto actual. Los parecidos salen del propio catálogo por palabras del título.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import random
from dataclasses import dataclass, field
from typing import Any

from ..comun import TZ_MX
from ..clasificador import COMODINES_CONOCIDOS
from .transporte import DatosApi, perfil_demo

SEMILLA = 20261112
HOST_IMAGENES = 'p16-corte-demo.ibyteimg.com'        # nunca se descarga: el descargador demo dibuja la imagen

# Las cifras del encabezado, en datos (test_sync_demo comprueba que el encabezado las dice y que la sync las reproduce).
CIFRAS: dict[str, int] = {
    'muestras': 108, 'pendientes': 34, 'vencidas': 30, 'por_vencer': 3, 'pausadas': 1, 'tiendas_con_pendientes': 25,
    'recibidas': 44, 'tiendas_recibidas': 27, 'entregadas': 6, 'exentas': 4, 'en_camino': 1, 'esperando_aprobacion': 3,
    'sin_envio': 60, 'pedido_cancelado': 0, 'deuda_pendiente': 28, 'video_no_vinculado': 1, 'producto_no_disponible': 1,
    'pedidos': 2501, 'reembolsados': 652, 'lineas': 2692, 'unidades': 2145, 'ventas_centavos': 83380500,
    'comision_total_centavos': 9656105, 'comision_liquidada_centavos': 8601401,
    'comision_por_liquidar_centavos': 818864, 'comision_retenida_centavos': 235840, 'tiendas_con_venta': 31,
    'productos_con_venta': 50, 'videos_con_venta': 90, 'pedidos_tienda_dominante': 1877,
}

TIENDA_DOMINANTE = 'Moda Aurora MX'
_NOMBRES_TIENDAS = (
    TIENDA_DOMINANTE, 'Casa Nube', 'Textiles Brisa', 'Luna Básicos', 'Hogar Cardinal', 'Tierra Clara Cosmética',
    'Vela Norte', 'Bambú Hogar', 'Cielo Activo', 'Ritmo Urbano', 'Café Sereno', 'Pétalo Belleza', 'Roble y Lino',
    'Nido Infantil', 'Mar Azul Swim', 'Faro Tech', 'Jade Accesorios', 'Ola Deportes', 'Nopal Natural', 'Cántaro Cocina',
    'Duna Calzado', 'Arena Fina', 'Brisa Hogar', 'Zafiro Joyería', 'Colibrí Kids', 'Maíz Dorado', 'Selva Pet',
    'Quetzal Moda', 'Viento Sur', 'Cobre Estudio', 'Lienzo Arte', 'Pino Outdoor', 'Alba Skin', 'Nube Gamer',
    'Mezcla Urbana', 'Coral Baño', 'Ámbar Velas', 'Hilo Fino', 'Cresta Fitness', 'Tule Organizadores')
_TIPOS_PRODUCTO = (
    ('Chamarra acolchada', 'Ropa > Chamarras', 499, 899), ('Sudadera oversize', 'Ropa > Sudaderas', 299, 459),
    ('Pantalón cargo', 'Ropa > Pantalones', 349, 529), ('Pijama de algodón', 'Ropa > Pijamas', 259, 399),
    ('Set de toallas', 'Hogar > Baño', 289, 419), ('Juego de sábanas', 'Hogar > Recámara', 399, 649),
    ('Crema hidratante', 'Belleza > Cuidado de la piel', 189, 289), ('Protector solar FPS 50', 'Belleza > Solares', 219, 319),
    ('Termo de acero', 'Cocina > Termos', 249, 349), ('Organizador de cajones', 'Hogar > Organización', 159, 239),
    ('Lámpara LED de escritorio', 'Hogar > Iluminación', 329, 479), ('Audífonos inalámbricos', 'Electrónica > Audio', 399, 699),
    ('Tenis deportivos', 'Calzado > Deportivo', 549, 849), ('Bolsa tote de lona', 'Accesorios > Bolsas', 199, 299),
    ('Mochila escolar', 'Accesorios > Mochilas', 379, 559), ('Botella deportiva', 'Deportes > Hidratación', 149, 219),
    ('Collar para perro', 'Mascotas > Paseo', 129, 199), ('Vela aromática', 'Hogar > Decoración', 169, 259),
    ('Aretes de plata', 'Joyería > Aretes', 279, 449), ('Leggings de compresión', 'Deportes > Ropa', 289, 429))
_ATRIBUTOS = ('clásico', 'premium', 'básico', 'de temporada', 'edición limitada', 'ligero', 'unisex', 'compacto')
_VARIANTES = (['Talla M'], ['Talla G'], ['Color negro'], ['Color arena'], ['Pieza única'])

DIA = 86400
PRODUCTOS_DOMINANTE = 8                 # los que venden de la tienda dominante (tiene 3 más sin ventas)
MAX_TIENDAS_PENDIENTES = 27             # tope de tiendas distintas entre las 34 pendientes (hay 25 con productos sin venta)
VENCIDAS_CON_VIDEO = 2                  # vencidas cuyo producto ya vendió con un video (deuda «video no vinculado»)


def _id(rng: random.Random, prefijo: str, digitos: int) -> str:
    return prefijo + ''.join(str(rng.randrange(10)) for _ in range(digitos - len(prefijo)))


def _monto(centavos: int) -> dict[str, str]:
    return {'amount': '${:,.2f}'.format(centavos / 100), 'currency': 'MXN'}


def color_de(texto: str) -> str:
    """Color estable '#rrggbb' (medio, legible) para el marcador de una tienda o producto."""
    h = hashlib.sha1(texto.encode('utf-8')).digest()
    return '#{:02x}{:02x}{:02x}'.format(70 + h[0] % 140, 70 + h[1] % 140, 70 + h[2] % 140)


def url_imagen(tipo: str, ref_id: str) -> str:
    return f'https://{HOST_IMAGENES}/obj/corte-demo/{tipo}/{ref_id}.png'


@dataclass
class Tienda:
    nombre: str
    shop_id: str
    color: str


@dataclass
class Producto:
    id: str
    tienda: int
    titulo: str
    categoria: str
    precio_min: int                     # centavos
    precio_max: int
    tasa_bp: int
    unidades: int
    abierta: bool                       # en colaboración abierta (la API de productos lo devuelve)
    en_vitrina: bool
    skus: list[str] = field(default_factory=list)


@dataclass
class Catalogo:
    tiendas: list[Tienda]
    productos: list[Producto]
    videos: list[str]
    por_id: dict[str, Producto] = field(default_factory=dict)


def catalogo() -> Catalogo:
    """Tiendas, productos y videos (no dependen de la fecha: el descargador demo los usa para dibujar marcadores)."""
    rng = random.Random(SEMILLA)
    tiendas = [Tienda(n, _id(rng, '7', 19), color_de(n)) for n in _NOMBRES_TIENDAS]
    productos: list[Producto] = []
    for t_idx in range(len(tiendas)):
        n_prod = PRODUCTOS_DOMINANTE + 3 if t_idx == 0 else 1 + rng.randrange(3)
        for _ in range(n_prod):
            tipo, cat, pmin, pmax = _TIPOS_PRODUCTO[rng.randrange(len(_TIPOS_PRODUCTO))]
            pid = _id(rng, '1739', 19)
            titulo = f'{tipo} {_ATRIBUTOS[rng.randrange(len(_ATRIBUTOS))]}'
            p = Producto(id=pid, tienda=t_idx, titulo=titulo, categoria=cat, precio_min=pmin * 100, precio_max=pmax * 100,
                         tasa_bp=800 + 100 * rng.randrange(13), unidades=50 + rng.randrange(5000),
                         abierta=rng.random() < 0.7, en_vitrina=rng.random() < 0.3)
            p.skus = [_id(rng, '1729', 19), _id(rng, '1729', 19)]
            productos.append(p)
    videos = [_id(rng, '7', 19) for _ in range(90)]
    c = Catalogo(tiendas=tiendas, productos=productos, videos=videos)
    c.por_id = {p.id: p for p in productos}
    return c


def _epoch_local(hoy: dt.date, dias_atras: int, hora: int, minuto: int = 0) -> int:
    d = hoy - dt.timedelta(days=dias_atras)
    return int(dt.datetime(d.year, d.month, d.day, hora, minuto, tzinfo=TZ_MX).timestamp())


# Mezcla de solicitudes: (grupo, cantidad). Suma 108.
MEZCLA: tuple[tuple[str, int], ...] = (
    ('vencida', 29), ('vencida_cupon', 1), ('por_vencer', 3), ('pausada', 1), ('entregada', 6), ('exenta', 4),
    ('tienda_no_envio', 2), ('en_camino', 1), ('sin_respuesta', 47), ('esperando_respuesta', 3), ('rechazada', 10),
    ('retirada', 1))


def generar(ahora: int) -> DatosApi:
    """Respuestas de la API sintética para un «ahora» dado (las fechas son relativas al día de hoy en México)."""
    cat = catalogo()
    rng = random.Random(SEMILLA + 1)
    hoy = dt.datetime.fromtimestamp(ahora, TZ_MX).date()
    tiendas, productos = cat.tiendas, cat.productos
    dom = [p for p in productos if p.tienda == 0][:PRODUCTOS_DOMINANTE]
    otros = [p for p in productos if p.tienda != 0]

    # ------------------------------------------------------------------ pedidos
    rangos = ((1, 30, 10), (31, 60, 24), (61, 90, 26), (91, 120, 18), (121, 150, 8), (151, 180, 5), (181, 240, 5),
              (241, 320, 4))
    pesos_rango = [w for _, _, w in rangos]
    vendidos_otros = otros[:]
    rng.shuffle(vendidos_otros)
    vendidos_otros = vendidos_otros[:41]
    pesos_video = [1.0 / (k + 1) ** 0.8 for k in range(len(cat.videos))]
    ordenes: list[dict[str, Any]] = []
    for k in range(2500):
        a, b, _w = rangos[rng.choices(range(len(rangos)), weights=pesos_rango)[0]]
        dias = a + rng.randrange(b - a + 1)
        ct = _epoch_local(hoy, dias, 8 + rng.randrange(12), rng.randrange(60))
        prod = dom[rng.randrange(len(dom))] if rng.random() < 0.75 else vendidos_otros[rng.randrange(len(vendidos_otros))]
        r = rng.random()
        if r < 0.25:
            estado = 'REFUNDED'
        elif dias <= 3 and r < 0.40:
            estado = 'AWAITING PAYMENT'
        elif dias <= 25:
            estado = 'To-SETTLE'
        elif r < 0.27:
            estado = 'FROZEN'
        else:
            estado = 'SETTLED'
        rv = rng.random()
        contenido, content_id = (('VIDEO', cat.videos[rng.choices(range(len(cat.videos)), weights=pesos_video)[0]])
                                 if rv < 0.85 else ('LIVE', _id(rng, '73', 19)) if rv < 0.95 else ('SHOP', None))
        n_lineas = 1 if rng.random() < 0.95 else 2 + rng.randrange(2)    # la misma SKU repetida (una fila por unidad)
        var = rng.randrange(2)
        precio = prod.precio_min if var == 0 else prod.precio_max
        cantidad = 1 if rng.random() < 0.9 else 2
        skus = []
        for _ in range(n_lineas):
            est = round(precio * cantidad * prod.tasa_bp / 10000)
            skus.append({'id': prod.skus[var], 'product_id': prod.id, 'product_name': prod.titulo,
                         'shop_name': tiendas[prod.tienda].nombre, 'price': _monto(precio), 'quantity': cantidad,
                         'refunded_quantity': cantidad if estado == 'REFUNDED' else 0, 'returned_quantity': 0,
                         'commission_rate': prod.tasa_bp, 'estimated_commission': _monto(est),
                         'actual_commission': _monto(est if estado == 'SETTLED' else 0),
                         'content_type': contenido, 'content_id': content_id, 'last_update_time': ct})
        ordenes.append({'id': _id(rng, '5770', 18), 'create_time': ct, 'status': estado, 'skus': skus})

    # ------------------------------------------------------------------ solicitudes de muestra
    con_venta = {p.id for p in dom} | {p.id for p in vendidos_otros}
    # Productos de las 34 pendientes: SIN ventas (su deuda queda «pendiente»), repartidos en hasta MAX_TIENDAS_PENDIENTES
    # tiendas (la dominante pone 3); las VENCIDAS_CON_VIDEO primeras vencidas usan un producto que ya vendió con video.
    sin_venta: dict[int, list[Producto]] = {}
    for p in productos:
        if p.id not in con_venta:
            sin_venta.setdefault(p.tienda, []).append(p)
    otras_t = sorted(t for t in sin_venta if t != 0)
    rng.shuffle(otras_t)
    otras_t = otras_t[:MAX_TIENDAS_PENDIENTES - 1]
    slots_pend = [0, 0, 0] + otras_t + otras_t[:34 - 3 - len(otras_t)]
    vendidos_video = [p for p in vendidos_otros if p.tienda in otras_t]
    solicitudes, filtros, envios, detalle = [], {}, [], {}
    t_pend = 0
    con_video_restantes = VENCIDAS_CON_VIDEO
    for grupo, cantidad in MEZCLA:
        for _ in range(cantidad):
            aid = _id(rng, '5772', 18)
            if grupo in ('vencida', 'vencida_cupon', 'por_vencer', 'pausada'):
                t_idx = slots_pend[t_pend]
                t_pend += 1
                cand = sin_venta[t_idx]
                if grupo == 'vencida' and t_idx != 0 and con_video_restantes > 0:
                    vendidos_t = [p for p in vendidos_video if p.tienda == t_idx]
                    if vendidos_t:
                        cand = vendidos_t
                        con_video_restantes -= 1
            else:
                cand = productos
            prod = cand[rng.randrange(len(cand))]
            # Como suele pasar con la API, toda muestra se pide de un producto en colaboración abierta: su ficha
            # trae título, precio, foto y el nombre de la tienda (nunca «Tienda …1234» ni un producto sin nombre).
            prod.abierta = True
            dias_sol = {'vencida': 50 + rng.randrange(70), 'vencida_cupon': 0, 'por_vencer': 10 + rng.randrange(10),
                        'pausada': 25, 'entregada': 60 + rng.randrange(90), 'exenta': 40 + rng.randrange(60),
                        'tienda_no_envio': 40 + rng.randrange(20), 'en_camino': 5, 'sin_respuesta': 35 + rng.randrange(55),
                        'esperando_respuesta': 3 + rng.randrange(8), 'rechazada': 20 + rng.randrange(80),
                        'retirada': 45}[grupo]
            estado_api = {'vencida': 'UNFULFILL_CANCELLED', 'vencida_cupon': 'UNKNOWN', 'por_vencer': 'CONTENT_PENDING',
                          'pausada': 'FULFILLMENT_SUSPEND', 'entregada': 'COMPLETED', 'exenta': 'CANCELED',
                          'tienda_no_envio': 'CANCELED', 'en_camino': 'SHIPPED', 'sin_respuesta': 'UNKNOWN',
                          'esperando_respuesta': 'UNKNOWN', 'rechazada': 'REJECT_CANCELLED',
                          'retirada': 'WITHDRAW_CANCELLED'}[grupo]
            con_pedido = grupo in ('vencida', 'vencida_cupon', 'por_vencer', 'pausada', 'entregada', 'exenta',
                                   'tienda_no_envio', 'en_camino')
            pedido = _id(rng, '5799', 18) if con_pedido else '0'
            tipo = 'SAMPLE_COUPON' if grupo == 'vencida_cupon' else 'FREE_SAMPLE'
            if grupo == 'vencida_cupon':
                # el pedido de la muestra con cupón ES un pedido de afiliado (lo pagaste): su fecha es la solicitud efectiva
                pct = _epoch_local(hoy, 70, 13)
                ordenes.append({'id': pedido, 'create_time': pct, 'status': 'SETTLED', 'skus': [{
                    'id': prod.skus[0], 'product_id': prod.id, 'product_name': prod.titulo,
                    'shop_name': tiendas[prod.tienda].nombre, 'price': _monto(4900), 'quantity': 1,
                    'refunded_quantity': 0, 'returned_quantity': 0, 'commission_rate': prod.tasa_bp,
                    'estimated_commission': _monto(round(4900 * prod.tasa_bp / 10000)),
                    'actual_commission': _monto(round(4900 * prod.tasa_bp / 10000)), 'content_type': 'SHOP',
                    'content_id': None, 'last_update_time': pct}]})
            solicitudes.append({'id': aid, 'status': estado_api, 'main_order_id': pedido, 'activity_id': '',
                                'sample_product': {'id': prod.id, 'sku_id': prod.skus[0],
                                                   'sku_sale_property_value_names': _VARIANTES[rng.randrange(len(_VARIANTES))]},
                                'creator_fulfillment': {'status': 'UNKNOWN'}})
            especificos = [] if estado_api == 'UNKNOWN' else [estado_api]
            if grupo == 'tienda_no_envio':
                especificos.append('SELLER_NOT_SHIP_CANCELLED')
            filtros[aid] = especificos
            detalle[aid] = {'create_time': 0 if grupo == 'vencida_cupon' else _epoch_local(hoy, dias_sol, 11),
                            'type': tipo, 'main_order_id': pedido if con_pedido else None}
            st_cumpl = {'vencida': 'OVERDUE', 'vencida_cupon': 'OVERDUE', 'por_vencer': 'PENDING', 'pausada': 'SUSPEND',
                        'entregada': 'SUCCEED', 'exenta': 'EXEMPTED'}.get(grupo)
            if st_cumpl:
                vence = (_epoch_local(hoy, -(3 + 3 * len([e for e in envios if e['status'] == 'PENDING'])), 23, 59)
                         if st_cumpl == 'PENDING' else ahora)
                envios.append({'id': _id(rng, '5801', 19), 'application_id': aid, 'product_id': prod.id,
                               'shop_id': tiendas[prod.tienda].shop_id, 'status': st_cumpl, 'expiration_time': vence,
                               'total_suspend_duration': 2 * DIA if st_cumpl == 'SUSPEND' else 0,
                               'bound_product_status': 'LIVE', 'sample_application_type': tipo})
    # una vencida con el producto agotado (deuda «producto no disponible»)
    for e in envios:
        if e['status'] == 'OVERDUE' and e['product_id'] not in con_venta and e['sample_application_type'] == 'FREE_SAMPLE':
            e['bound_product_status'] = 'OUT_OF_STOCK'
            break

    # ------------------------------------------------------------------ productos (colaboración abierta) y vitrina
    abiertos = {}
    for p in productos:
        if not p.abierta:
            continue
        t = tiendas[p.tienda]
        com_min, com_max = round(p.precio_min * p.tasa_bp / 10000), round(p.precio_max * p.tasa_bp / 10000)
        cats = [{'id': str(600000 + k), 'local_name': n} for k, n in enumerate(p.categoria.split(' > '))]
        abiertos[p.id] = {
            'id': p.id, 'title': p.titulo, 'main_image_url': url_imagen('p', p.id),
            'detail_link': f'https://shop.tiktok.com/view/product/{p.id}?region=MX&local=es',
            'original_price': {'minimum_amount': f'{p.precio_min / 100:.2f}', 'maximum_amount': f'{p.precio_max / 100:.2f}',
                               'currency': 'MXN'},
            'commission': {'rate': p.tasa_bp, 'amount': f'{com_min / 100:.2f} - {com_max / 100:.2f}', 'currency': 'MXN'},
            'units_sold': p.unidades, 'has_inventory': True, 'category_chains': cats, 'sale_region': 'MX',
            'shop': {'name': t.nombre}}
    vitrina = []
    for p in productos:
        if not p.en_vitrina:
            continue
        t = tiendas[p.tienda]
        desc_min, desc_max = round(p.precio_min * 0.9), round(p.precio_max * 0.9)
        vitrina.append({'id': p.id, 'title': p.titulo, 'shop': {'name': t.nombre},
                        'main_images': [{'url': url_imagen('p', p.id)}],
                        'price': {'original_price': {'minimum_amount': f'{p.precio_min / 100:.2f}',
                                                     'maximum_amount': f'{p.precio_max / 100:.2f}'},
                                  'seller_discount_price': {'minimum_amount': f'{desc_min / 100:.2f}',
                                                            'maximum_amount': f'{desc_max / 100:.2f}'}},
                        'detail_link': f'https://shop.tiktok.com/view/product/{p.id}?region=MX&local=es'})
    datos = DatosApi(perfil=perfil_demo(None), solicitudes=solicitudes, filtros=filtros,
                     comodines=frozenset(COMODINES_CONOCIDOS), envios=envios, detalle=detalle, productos=abiertos,
                     ordenes=ordenes, vitrina=vitrina, ahora=ahora)
    _ficha_completa(datos, cat, dom, hoy, ahora)
    return datos


# ====================================================================== rev. 4: ficha completa de producto
TASA_PLAN_ABIERTO_MENOS_BP = 400        # los 2 productos de la «comisión real»: plan abierto actual = tasa − 4 puntos
_COLORES = ('Negro', 'Arena', 'Azul marino', 'Blanco', 'Verde olivo')
_TALLAS = ('CH', 'M', 'G', 'EG')
_CON_TALLA = ('Ropa', 'Calzado', 'Deportes > Ropa')


def _props_sku(rng: random.Random, p: Producto, k: int) -> list[dict[str, str]]:
    color = _COLORES[(int(p.id[-2:]) + k) % len(_COLORES)]
    props = [{'id': '100000', 'name': 'Color', 'value_id': _id(rng, '7', 19), 'value_name': color}]
    if p.categoria.startswith(_CON_TALLA):
        props.append({'id': '100007', 'name': 'Talla', 'value_id': _id(rng, '7', 19),
                      'value_name': _TALLAS[(int(p.id[-3:]) + k) % len(_TALLAS)]})
    return props


def _ficha_completa(d: DatosApi, cat: Catalogo, dom: list[Producto], hoy: dt.date, ahora: int) -> None:
    """Agrega a `d` los datos de la ficha completa con un generador APARTE (las cifras documentadas no se mueven)."""
    rng = random.Random(SEMILLA + 4)
    tiendas = cat.tiendas
    por_shop = {t.shop_id: i for i, t in enumerate(tiendas)}
    # --- single_query trae el SKU y la variante de cada solicitud (como la API real)
    for s in d.solicitudes:
        d.detalle[s['id']]['sample_product'] = dict(s['sample_product'])
        d.detalle[s['id']]['status'] = s['status']
    # --- una solicitud que NO sale en la búsqueda: solo se conoce por su cumplimiento (mismo producto y tienda que la
    # primera entregada, así su tienda ya tiene nombre); su SKU y su variante salen de single_query
    base = next(e for e in d.envios if e['status'] == 'SUCCEED')
    prod_base = cat.por_id[base['product_id']]
    huerfana = _id(rng, '5773', 18)
    d.envios.append({'id': _id(rng, '5802', 19), 'application_id': huerfana, 'product_id': base['product_id'],
                     'shop_id': base['shop_id'], 'status': 'SUCCEED', 'expiration_time': ahora,
                     'total_suspend_duration': 0, 'bound_product_status': 'LIVE', 'sample_application_type': 'FREE_SAMPLE'})
    d.detalle[huerfana] = {'create_time': _epoch_local(hoy, 120, 12), 'type': 'FREE_SAMPLE',
                           'main_order_id': _id(rng, '5799', 18), 'status': 'COMPLETED',
                           'sample_product': {'id': prod_base.id, 'sku_id': prod_base.skus[1],
                                              'sku_sale_property_value_names': [p['value_name'] for p in
                                                                                _props_sku(rng, prod_base, 1)]}}
    # --- elegibilidad de muestra (samples/labels) para todo el catálogo
    sols_por_prod: dict[str, list[dict[str, Any]]] = {}
    for s in d.solicitudes:
        sols_por_prod.setdefault(s['sample_product']['id'], []).append(s)
    envio_por_app = {e['application_id']: e for e in d.envios}
    for p in cat.productos:
        sols = sols_por_prod.get(p.id, [])
        estados = {(envio_por_app.get(s['id']) or {}).get('status') for s in sols}
        if estados & {'PENDING', 'ONGOING', 'SUSPEND'}:
            status, puede = 'ONGOING', False
        elif 'SUCCEED' in estados:
            status, puede = 'COMPLETE', False
        elif sols:
            status, puede = 'UNKNOWN', rng.random() < 0.5
        else:
            status, puede = 'TO_APPLY', rng.random() < 0.8
        pedida = sols[-1]['sample_product']['sku_id'] if sols else None
        skus = []
        for k, sku in enumerate(p.skus):
            agotado = k == 1 and int(p.id[-1]) % 4 == 0
            ya = sku == pedida and status in ('ONGOING', 'COMPLETE')
            props = _props_sku(rng, p, k)
            skus.append({'id': sku, 'sale_property_value_ids': '_'.join(x['value_id'] for x in props), 'price': {
                'amount': f'{(p.precio_min if k == 0 else p.precio_max) / 100:.2f}', 'currency': 'MXN'},
                'sale_properties': props, 'is_available': not (agotado or ya),
                'unavailable_reason': 'ALREADY_APPLYED' if ya else 'OUT_OF_STOCK' if agotado else 'UNKNOWN'})
        label: dict[str, Any] = {'can_apply': puede, 'status': status, 'reach_limit': False,
                                 'sample_product': {'sample_sku_list': skus}}
        if status in ('ONGOING', 'COMPLETE'):
            label['application_id'] = sols[-1]['id']
        d.etiquetas[p.id] = label
    # --- planes dirigidos (target_collaborations) de las tiendas con shop_id; la «comisión real» de Moda Aurora MX:
    # los 2 productos de la tienda dominante con la tasa más alta (también en tu vitrina, para que su ficha salga completa)
    abiertos_dom = sorted((p for p in dom if p.id in d.productos), key=lambda p: (-p.tasa_bp, p.id))[:2]
    en_vitrina = {v['id'] for v in d.vitrina}
    for p in abiertos_dom:
        if p.id not in en_vitrina:
            d.vitrina.append({'id': p.id, 'title': p.titulo, 'shop': {'name': tiendas[p.tienda].nombre},
                              'main_images': [{'url': url_imagen('p', p.id)}],
                              'price': {'original_price': {'minimum_amount': f'{p.precio_min / 100:.2f}',
                                                           'maximum_amount': f'{p.precio_max / 100:.2f}'},
                                        'seller_discount_price': {
                                            'minimum_amount': f'{round(p.precio_min * 0.9) / 100:.2f}',
                                            'maximum_amount': f'{round(p.precio_max * 0.9) / 100:.2f}'}},
                              'detail_link': f'https://shop.tiktok.com/view/product/{p.id}?region=MX&local=es'})
    campana = _id(rng, '7606', 19)
    for p in abiertos_dom:                       # el plan abierto ACTUAL paga menos que lo que pagaron tus ventas
        f = d.productos[p.id]
        tasa = max(400, p.tasa_bp - TASA_PLAN_ABIERTO_MENOS_BP)
        cmin, cmax = round(p.precio_min * tasa / 10000), round(p.precio_max * tasa / 10000)
        f['commission'] = {'rate': tasa, 'amount': f'{cmin / 100:.2f} - {cmax / 100:.2f}', 'currency': 'MXN'}
        f['shop_ads_commission'] = {'rate': 300}
    ids_campana = {p.id for p in abiertos_dom}
    for o in d.ordenes:
        for s in o['skus']:
            if s['product_id'] in ids_campana:
                s['campaign_id'] = campana

    def producto_plan(p: Producto, tasa: int) -> dict[str, Any]:
        return {'id': p.id, 'title': p.titulo, 'main_image_url': url_imagen('p', p.id),
                'commission': {'rate': tasa, 'amount': f'{round(p.precio_min * tasa / 10000) / 100:.2f}',
                               'currency': 'MXN'}}

    for sid in sorted({e['shop_id'] for e in d.envios if e.get('shop_id')}):
        t_idx = por_shop.get(sid)
        if t_idx is None:
            continue
        propios = [p for p in cat.productos if p.tienda == t_idx]
        planes: list[dict[str, Any]] = []
        if t_idx == 0:
            planes.append({'id': _id(rng, '7311', 19), 'name': 'Temporada Aurora', 'status': 'LIVE',
                           'products': [producto_plan(p, p.tasa_bp) for p in abiertos_dom]})
            otros = [p for p in propios if p.id not in ids_campana][:1]
            planes.append({'id': _id(rng, '7311', 19), 'name': 'Buen Fin Aurora', 'status': 'EXPIRED',
                           'products': [producto_plan(p, p.tasa_bp + 300) for p in otros]})
        elif rng.random() < 0.4:
            elegidos = propios[:1 + rng.randrange(min(2, len(propios)))]
            planes.append({'id': _id(rng, '7311', 19), 'name': f'Creadores {tiendas[t_idx].nombre}',
                           'status': 'LIVE' if rng.random() < 0.6 else 'EXPIRED',
                           'products': [producto_plan(p, p.tasa_bp + 100 * (1 + rng.randrange(4))) for p in elegidos]})
        d.dirigidas[sid] = planes
    # --- enlace de cada línea (trace_info de orders/search 202410): general o para un publicador en algunas líneas
    for o in d.ordenes:
        tipos: list[str | None] = []
        for s in o['skus']:
            r = rng.random()
            tipos.append('GENERAL' if r < 0.12 else 'SPECIFIC' if r < 0.15 else None)
        d.trazas[o['id']] = tipos
    # --- vitrina: galería de 5 a 9 fotos (la 1.ª es la del producto), inventario y descuento de la plataforma
    for v in d.vitrina:
        p = cat.por_id[v['id']]
        n_fotos = 5 + int(p.id[-1]) % 5
        v['main_images'] = [{'url': url_imagen('p', p.id), 'width': 800, 'heigth': 800}] + [
            {'url': url_imagen('g', f'{p.id}-{n}'), 'width': 800, 'heigth': 800} for n in range(1, n_fotos)]
        v['status'] = {'inventory_status': 'SOLD_OUT' if int(p.id[-2:]) % 8 == 0 else 'IN_STOCK',
                       'review_status': 'APPROVED', 'added_status': 'ADDED', 'is_hidden': False}
        v['price']['original_price']['currency'] = 'MXN'
        v['price']['seller_discount_price']['currency'] = 'MXN'
        v['price']['platform_discount_price'] = {'minimum_amount': f'{round(p.precio_min * 0.85) / 100:.2f}',
                                                 'maximum_amount': f'{round(p.precio_max * 0.85) / 100:.2f}',
                                                 'currency': 'MXN'}
        v['commission'] = {'rate': p.tasa_bp}
        v['source'] = 'AFFILIATE'
        v['collaboration'] = {'type': '1'}
