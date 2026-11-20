"""Páginas de estado del hub que también se leen sin la interfaz instalada."""
from html import escape

from .identidad_generada import MARCA, TEMA


def pagina_estado(titulo: str, mensaje: str, *, correcto: bool = False) -> bytes:
    estilo = (
        '*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;'
        'padding:24px;background:var(--canvas);color:var(--ink);font:1rem/1.5 system-ui,sans-serif}'
        'main{width:min(100%,32rem);overflow:hidden;border:1px solid var(--line);'
        'border-radius:12px;background:var(--surface)}header{background:var(--chrome);padding:24px}'
        'header svg{display:block;width:8rem;height:auto}section{padding:24px}h1{margin:0;'
        'font-size:1.5rem;line-height:1.2;letter-spacing:-.025em}p{margin:12px 0 0;color:var(--muted);'
        'overflow-wrap:anywhere}section{border-top:3px solid var(--danger)}'
        'section.ok{border-color:var(--success)}'
    )
    heading = escape(titulo)
    estado = 'ok' if correcto else 'aviso'
    return (
        '<!doctype html><html lang="es-MX"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{heading} · CUTGC</title><style>{TEMA}{estilo}</style></head>'
        f'<body><main><header>{MARCA}</header><section class="{estado}"><h1>{heading}</h1>'
        f'<p>{escape(mensaje)}</p></section></main></body></html>'
    ).encode('utf-8')
