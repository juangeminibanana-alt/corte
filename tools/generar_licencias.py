# -*- coding: utf-8 -*-
"""licencias.json de Corte (Ajustes › Acerca de › Licencias; BUILD_SPEC §13, build-empaquetado).

Uso (lo llama scripts\\generar_licencias.ps1, después de `npm run build` en build_windows.ps1 y build_android.ps1):
    .venv-hub\\Scripts\\python.exe -I tools\\generar_licencias.py --raiz <proyecto> --salida <ui\\dist\\licencias.json>
                                     [--plataforma windows|android]

Qué incluye, con el TEXTO de cada licencia tal como viene en el paquete instalado (nada se resume ni se inventa):
  - origen «interfaz»: cada dependencia de ejecución de ui/package-lock.json (todas las entradas sin «dev» ni
    «devOptional»; las transitivas también), con la versión del lock y los archivos LICENSE/COPYING/NOTICE de
    ui/node_modules/<paquete>. Fuentes OFL-1.1, jsQR Apache-2.0, lucide ISC, React y el resto MIT.
  - origen «ejecutable» (solo --plataforma windows; el APK no lleva nada más que la interfaz): los paquetes de la
    sección «entran en CreatorHub.exe» de hub/requirements.txt, con los archivos de licencia de su .dist-info en el
    .venv-hub (pywebview, pythonnet, Pillow, qrcode, …); Python (intérprete, biblioteca estándar y las bibliotecas de su
    compilación de Windows: OpenSSL, libffi, SQLite, bzip2, xz, zlib…, texto de LICENSE.txt de la instalación); el
    cargador de WebView2 que trae pywebview (Microsoft.Web.WebView2.Core/WinForms y WebView2Loader.dll) y el cargador
    (bootloader) de PyInstaller que va dentro del .exe.

Antes de escribir comprueba que: cada paquete del lock está en node_modules con la misma versión; cada requisito del exe
está instalado con la versión fijada; cada componente tiene licencia SPDX y texto; y el JSON no trae «fixtures»,
«creador_demo», «__DOBLE_CORTE__» ni un patrón de secreto (verificar_dist y la guardia los rechazan). Si algo falla,
sale con 1 y no escribe nada. La salida es determinista (sin fechas): mismo lock y mismo venv, mismo archivo.
"""
from __future__ import annotations

import argparse
import ctypes
import importlib.metadata as md
import json
import os
import platform
import re
import sys

FORMATO = 1
ARCHIVO_LICENCIA = re.compile(r'^(licen[cs]e|copying|notice)([._-].*)?$', re.I)
# SPDX de los paquetes del exe que no declaran License-Expression (revisado contra su texto). Si un paquete nuevo entra en
# requirements.txt sin License-Expression, el script falla hasta que alguien lo agregue aquí después de leer su licencia.
SPDX_EXE = {
    'pywebview': 'BSD-3-Clause', 'proxy_tools': 'MIT', 'bottle': 'MIT', 'typing_extensions': 'PSF-2.0',
    'pythonnet': 'MIT', 'clr_loader': 'MIT', 'cffi': 'MIT-0', 'pycparser': 'BSD-3-Clause', 'qrcode': 'BSD-3-Clause',
    'colorama': 'BSD-3-Clause', 'pypng': 'MIT', 'pillow': 'MIT-CMU',
}
PROHIBIDO_EN_SALIDA = [
    (re.compile(r'fixtures', re.I), '«fixtures»'),
    (re.compile(r'creador_demo'), '«creador_demo»'),
    (re.compile(r'__DOBLE_CORTE__'), '«__DOBLE_CORTE__»'),
    (re.compile(r'"(app_secret|access_token|refresh_token)"\s*:\s*"[^"]{8,}"'), 'un patrón de secreto'),
]
WEBVIEW2_DLLS = ('lib/Microsoft.Web.WebView2.Core.dll', 'lib/Microsoft.Web.WebView2.WinForms.dll',
                 'lib/runtimes/win-x64/native/WebView2Loader.dll')


class ErrorLicencias(Exception):
    pass


def leer(ruta: str) -> str:
    with open(ruta, encoding='utf-8', errors='replace') as f:
        return f.read().replace('\r\n', '\n').strip() + '\n'


def norm(nombre: str) -> str:
    return re.sub(r'[-_.]+', '_', nombre).lower()


# ====================================================================== interfaz (npm)
def componentes_interfaz(raiz: str) -> list[dict]:
    ui = os.path.join(raiz, 'ui')
    with open(os.path.join(ui, 'package-lock.json'), encoding='utf-8') as f:
        lock = json.load(f)
    if lock.get('lockfileVersion') not in (2, 3):
        raise ErrorLicencias(f"ui/package-lock.json con lockfileVersion {lock.get('lockfileVersion')} (se esperaba 2 o 3)")
    salida = []
    for clave, info in sorted(lock['packages'].items()):
        if not clave or info.get('dev') or info.get('devOptional') or info.get('link'):
            continue
        nombre = info.get('name') or clave.rsplit('node_modules/', 1)[-1]
        carpeta = os.path.join(ui, *clave.split('/'))
        pj = os.path.join(carpeta, 'package.json')
        if not os.path.isfile(pj):
            if info.get('optional'):
                continue                         # opcional de otra plataforma: no se instaló, no viaja
            raise ErrorLicencias(f'Falta {clave} en ui/node_modules (corre npm ci en ui/)')
        with open(pj, encoding='utf-8') as f:
            paquete = json.load(f)
        if paquete.get('version') != info.get('version'):
            raise ErrorLicencias(f"{nombre}: node_modules tiene {paquete.get('version')} y el lock {info.get('version')} (corre npm ci)")
        licencia = info.get('license') or paquete.get('license')
        if isinstance(licencia, dict):
            licencia = licencia.get('type')
        archivos = sorted((a for a in os.listdir(carpeta) if ARCHIVO_LICENCIA.match(a) and os.path.isfile(os.path.join(carpeta, a))),
                          key=lambda a: (not a.lower().startswith('licen'), a.lower()))
        if not archivos:
            raise ErrorLicencias(f'{nombre} {info["version"]} no trae archivo de licencia en node_modules')
        texto = '\n\n'.join(leer(os.path.join(carpeta, a)) for a in archivos)
        repo = paquete.get('repository')
        if isinstance(repo, dict):
            repo = repo.get('url')
        sitio = paquete.get('homepage') or repo
        if isinstance(sitio, str):
            sitio = re.sub(r'^git\+', '', sitio).removesuffix('.git')
        salida.append({'nombre': nombre, 'version': info['version'], 'licencia': licencia, 'origen': 'interfaz',
                       'descripcion': None, 'sitio': sitio or None, 'archivos_licencia': archivos, 'nota': None,
                       'texto': texto})
    if not salida:
        raise ErrorLicencias('ui/package-lock.json no tiene dependencias de ejecución')
    return salida


# ====================================================================== ejecutable (Python)
def requisitos_exe(raiz: str) -> list[tuple[str, str]]:
    """(nombre, versión) de la sección «entran en CreatorHub.exe» de hub/requirements.txt."""
    dentro, salida = False, []
    with open(os.path.join(raiz, 'hub', 'requirements.txt'), encoding='utf-8') as f:
        for linea in f:
            s = linea.strip()
            if s.startswith('# ---'):
                dentro = 'entran en CreatorHub.exe' in s
                continue
            if not dentro or not s or s.startswith('#'):
                continue
            m = re.match(r'^([A-Za-z0-9_.\-]+)==([^\s#]+)', s)
            if not m:
                raise ErrorLicencias(f'hub/requirements.txt: línea sin versión exacta en la sección del exe: {s}')
            salida.append((m.group(1), m.group(2)))
    if not salida:
        raise ErrorLicencias('hub/requirements.txt no tiene la sección «# --- entran en CreatorHub.exe»')
    return salida


def archivos_licencia_dist(dist: md.Distribution) -> list[tuple[str, str]]:
    """(nombre relativo, ruta) de los archivos de licencia del .dist-info (PEP 639 licenses/ o en la raíz)."""
    base = str(dist.locate_file(''))
    encontrados = []
    for f in dist.files or []:
        partes = f.parts
        if len(partes) < 2 or not partes[0].endswith('.dist-info'):
            continue
        en_licenses = len(partes) > 2 and partes[1] == 'licenses'
        en_raiz = len(partes) == 2 and ARCHIVO_LICENCIA.match(partes[1])
        if en_licenses or en_raiz:
            encontrados.append(('/'.join(partes[1:]), os.path.join(base, *partes)))
    return sorted(encontrados, key=lambda x: (not x[0].split('/')[-1].lower().startswith(('licen', 'copying')), x[0].lower()))


def sitio_dist(m) -> str | None:
    urls = {}
    for u in m.get_all('Project-URL') or []:
        etiqueta, _, url = u.partition(',')
        urls[etiqueta.strip().lower()] = url.strip()
    for k in ('homepage', 'home', 'source', 'sources', 'repository', 'source code'):
        if urls.get(k):
            return urls[k]
    return m.get('Home-page') or None


def componente_python_paquete(nombre: str, fijada: str, raiz: str) -> dict:
    try:
        dist = md.distribution(nombre)
    except md.PackageNotFoundError:
        raise ErrorLicencias(f'{nombre} no está instalado en .venv-hub (corre scripts\\preparar_entorno.ps1)') from None
    if dist.version != fijada:
        raise ErrorLicencias(f'{nombre}: .venv-hub tiene {dist.version} y requirements.txt fija {fijada} (corre preparar_entorno)')
    m = dist.metadata
    clave = norm(m['Name'])
    expresion = m.get('License-Expression')
    tabla = SPDX_EXE.get(clave)
    if expresion and tabla and expresion != tabla:
        raise ErrorLicencias(f'{nombre}: declara {expresion} pero la tabla SPDX_EXE dice {tabla}: revisa su licencia')
    licencia = expresion or tabla
    if not licencia:
        raise ErrorLicencias(f'{nombre} no declara License-Expression: lee su licencia y agrégala a SPDX_EXE')
    archivos = archivos_licencia_dist(dist)
    nota = None
    if archivos:
        texto = '\n\n'.join(leer(r) for _, r in archivos)
        nombres = [a for a, _ in archivos]
    elif licencia == 'MIT':
        titulares = m.get('Author') or m.get('Author-email') or m['Name']
        texto = leer(os.path.join(raiz, 'tools', 'licencias', 'MIT.txt')).replace('{titulares}', titulares)
        nombres = []
        nota = f'El paquete no incluye archivo de licencia; se reproduce el texto MIT estándar con el autor que declara ({titulares}).'
    else:
        raise ErrorLicencias(f'{nombre} ({licencia}) no trae archivo de licencia en su .dist-info')
    return {'nombre': m['Name'], 'version': dist.version, 'licencia': licencia, 'origen': 'ejecutable',
            'descripcion': None, 'sitio': sitio_dist(m), 'archivos_licencia': nombres, 'nota': nota, 'texto': texto}


def version_archivo(ruta: str) -> str:
    """Versión de archivo (VS_FIXEDFILEINFO) de un .dll de Windows, p. ej. '1.0.3856.49'."""
    v = ctypes.windll.version
    v.GetFileVersionInfoSizeW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p]
    v.GetFileVersionInfoW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    v.VerQueryValueW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint)]
    n = v.GetFileVersionInfoSizeW(ruta, None)
    if not n:
        raise ErrorLicencias(f'{ruta} no tiene recurso de versión')
    buf = ctypes.create_string_buffer(n)
    if not v.GetFileVersionInfoW(ruta, 0, n, buf):
        raise ErrorLicencias(f'No se pudo leer la versión de {ruta}')
    p, largo = ctypes.c_void_p(), ctypes.c_uint()
    if not v.VerQueryValueW(buf, '\\', ctypes.byref(p), ctypes.byref(largo)):
        raise ErrorLicencias(f'No se pudo leer VS_FIXEDFILEINFO de {ruta}')
    campos = (ctypes.c_uint32 * 13).from_address(p.value)
    ms, ls = campos[2], campos[3]
    return f'{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}'


def componentes_exe(raiz: str) -> list[dict]:
    salida = [componente_python_paquete(n, v, raiz) for n, v in requisitos_exe(raiz)]

    licencia_py = os.path.join(sys.base_prefix, 'LICENSE.txt')
    if not os.path.isfile(licencia_py):
        raise ErrorLicencias(f'Falta {licencia_py} (LICENSE.txt de la instalación de Python)')
    salida.append({'nombre': 'Python', 'version': platform.python_version(), 'licencia': 'PSF-2.0', 'origen': 'ejecutable',
                   'descripcion': 'Intérprete, biblioteca estándar y bibliotecas de su compilación de Windows '
                                  '(OpenSSL, libffi, SQLite, bzip2, xz, zlib…)',
                   'sitio': 'https://www.python.org/', 'archivos_licencia': ['LICENSE.txt'],
                   'nota': 'Incluye las licencias de las bibliotecas de terceros que trae Python para Windows.',
                   'texto': leer(licencia_py)})

    webview = md.distribution('pywebview')
    dlls = [str(webview.locate_file(os.path.join('webview', *d.split('/')))) for d in WEBVIEW2_DLLS]
    for d in dlls:
        if not os.path.isfile(d):
            raise ErrorLicencias(f'Falta {d} (cargador de WebView2 de pywebview)')
    versiones = sorted({version_archivo(d) for d in dlls})
    salida.append({'nombre': 'Microsoft.Web.WebView2', 'version': ', '.join(versiones), 'licencia': 'BSD-3-Clause',
                   'origen': 'ejecutable',
                   'descripcion': 'Cargador de WebView2: ' + ', '.join(os.path.basename(d) for d in dlls),
                   'sitio': 'https://developer.microsoft.com/microsoft-edge/webview2/',
                   'archivos_licencia': [],
                   'nota': 'pywebview incluye estos binarios del SDK de WebView2 sin su archivo de licencia; '
                           'se reproduce la licencia publicada del SDK (paquete Microsoft.Web.WebView2).',
                   'texto': leer(os.path.join(raiz, 'tools', 'licencias', 'Microsoft.Web.WebView2.txt'))})

    pyi = md.distribution('pyinstaller')
    archivos = archivos_licencia_dist(pyi)
    if not archivos:
        raise ErrorLicencias('PyInstaller no trae COPYING.txt en su .dist-info')
    salida.append({'nombre': 'PyInstaller (cargador del ejecutable)', 'version': pyi.version,
                   'licencia': 'GPL-2.0-or-later WITH Bootloader-exception', 'origen': 'ejecutable',
                   'descripcion': 'Solo el cargador (bootloader) que arranca CreatorHub.exe',
                   'sitio': 'https://pyinstaller.org', 'archivos_licencia': [a for a, _ in archivos],
                   'nota': 'La excepción del cargador permite distribuirlo dentro de cualquier programa.',
                   'texto': '\n\n'.join(leer(r) for _, r in archivos)})
    return salida


# ====================================================================== armado y verificación
def generar(raiz: str, plataforma: str) -> dict:
    with open(os.path.join(raiz, 'version.json'), encoding='utf-8') as f:
        version = json.load(f)['version']
    componentes = componentes_interfaz(raiz)
    if plataforma == 'windows':
        componentes += componentes_exe(raiz)
    orden = {'interfaz': 0, 'ejecutable': 1}
    componentes.sort(key=lambda c: (orden[c['origen']], c['nombre'].lower()))
    nombres = [(c['origen'], norm(c['nombre'])) for c in componentes]
    if len(set(nombres)) != len(nombres):
        raise ErrorLicencias('Componente repetido en licencias.json')
    for c in componentes:
        for campo in ('nombre', 'version', 'licencia', 'texto'):
            if not c.get(campo):
                raise ErrorLicencias(f"{c.get('nombre')}: falta «{campo}»")
        if len(c['texto']) < 300:
            raise ErrorLicencias(f"{c['nombre']}: el texto de la licencia es demasiado corto ({len(c['texto'])} caracteres)")
    return {'formato': FORMATO, 'producto': 'Corte', 'version': version, 'plataforma': plataforma, 'componentes': componentes}


def salida_como_la_consola() -> None:
    """PowerShell 5.1 decodifica la salida de un programa con la página de códigos de la consola; Python escribe en la
    del sistema (cp1252) cuando su salida va a una tubería. Se alinean para que los acentos lleguen bien."""
    try:
        cp = ctypes.windll.kernel32.GetConsoleOutputCP()
        cod = 'utf-8' if cp in (0, 65001) else f'cp{cp}'
        sys.stdout.reconfigure(encoding=cod, errors='replace')
        sys.stderr.reconfigure(encoding=cod, errors='replace')
    except (AttributeError, LookupError, OSError):
        pass


def main(argv: list[str] | None = None) -> int:
    salida_como_la_consola()
    ap = argparse.ArgumentParser(description='Genera licencias.json de Corte')
    ap.add_argument('--raiz', required=True)
    ap.add_argument('--salida', required=True)
    ap.add_argument('--plataforma', choices=('windows', 'android'), default='windows')
    a = ap.parse_args(argv)
    try:
        datos = generar(os.path.abspath(a.raiz), a.plataforma)
        texto = json.dumps(datos, ensure_ascii=False, indent=2) + '\n'
        for patron, nombre in PROHIBIDO_EN_SALIDA:
            if patron.search(texto):
                raise ErrorLicencias(f'licencias.json contendría {nombre}: verificar_dist y la guardia lo rechazarían')
    except (ErrorLicencias, OSError, ValueError, KeyError) as e:
        print(f'generar_licencias: FALLA · {e}', file=sys.stderr)
        return 1
    os.makedirs(os.path.dirname(os.path.abspath(a.salida)), exist_ok=True)
    temporal = a.salida + '.tmp'
    with open(temporal, 'w', encoding='utf-8', newline='\n') as f:
        f.write(texto)
    os.replace(temporal, a.salida)
    por_origen: dict[str, int] = {}
    for c in datos['componentes']:
        por_origen[c['origen']] = por_origen.get(c['origen'], 0) + 1
    detalle = ' · '.join(f'{n} de {o}' for o, n in por_origen.items())
    print(f"generar_licencias: OK · {a.salida} · {len(datos['componentes'])} componentes ({detalle}) · "
          f"{len(texto.encode('utf-8')) / 1000:.1f} KB · plataforma {a.plataforma}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
