# -*- coding: utf-8 -*-
"""Guardia profunda del paquete de Windows de Corte (04 §D.2 paso 5 con BUILD_SPEC C3 y §11.6; build-empaquetado).

Uso (la llama scripts\\guardia_exe.ps1, paso 5 de build_windows.ps1):
    .venv-hub\\Scripts\\python.exe -I tools\\guardia_exe.py <carpeta onedir> [--exigir PIL,qrcode,...] [--json <informe>]
Sale con 0 si no hay hallazgos, 1 si encuentra algo prohibido (una línea «PROHIBIDO: …» por hallazgo; nunca imprime el
valor de un secreto), 2 si la carpeta o el .exe no se pueden leer.

Lo que revisa, además de los nombres de archivo de la carpeta:
  1. Rutas: ningún segmento research, datos-reales, fixtures*, ejemplos*, verificacion, pruebas o _dobles; ningún .map;
     ningún archivo prohibido (config.json, *.dpapi, *.sqlite*, *.key, *.jks, *.keystore, *.env, *.ps1, *.pem salvo
     cacert.pem). Vale para los archivos de la carpeta, las entradas del CArchive del .exe y los módulos del PYZ.
  2. Lo que debía excluirse (C3: Pillow SÍ va): setuptools, pkg_resources, _distutils_hack y las dependencias de
     compilación (PyInstaller, altgraph, pefile, win32ctypes, packaging, pip), como carpeta en _internal o como módulo.
  3. Contenido: las cadenas creador_demo y __DOBLE_CORTE__ (ASCII y UTF-16LE) y el patrón de secreto de 04 §D.2 en
     cada archivo de la carpeta, en cada entrada DESCOMPRIMIDA del CArchive del .exe, en cada módulo DESCOMPRIMIDO del
     PYZ y en cada entrada de los .zip (base_library.zip). Buscar solo en los bytes del .exe no basta: PyInstaller
     comprime cada módulo con zlib.
     Excepción única: 'creador_demo' es la identidad de demostración de los datos sintéticos que sí viajan en el exe
     (BUILD §6.3 «Modo demo empaquetado»; hub-sync la define en creatorhub.demo.transporte.USUARIO_DEMO). Se permite
     SOLO dentro de ese módulo; en cualquier otro módulo, en la interfaz o en un archivo de datos es una fuga.
  4. --exigir: módulos que deben estar en el PYZ (build_windows exige PIL, qrcode, png, webview y creatorhub).
  5. Datos privados (BUILD §11.6): el username, el creator_user_open_id y la URL del avatar REALES de
     research/datos-reales/perfil.json (o del archivo de --perfil-privado) en los mismos lugares que el punto 3: exactos
     (UTF-8 y UTF-16LE) en todo y, sin distinguir mayúsculas, en código y archivos de texto. En binarios solo se buscan
     valores de 6 o más caracteres (evita coincidencias de azar). Los hallazgos nombran el CAMPO, nunca el valor. Si el
     archivo no existe (otra PC, sin research/), lo dice con un AVISO y sigue.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import zipfile

MARCADORES = (b'creador_demo', b'__DOBLE_CORTE__')
PERMITIDOS = {b'creador_demo': frozenset({'creatorhub.demo.transporte'})}
PATRON_SECRETO = re.compile(rb'"(app_secret|access_token|refresh_token)"\s*:\s*"[^"]{8,}"')
SEGMENTO_PROHIBIDO = re.compile(r'^(research|datos-reales|fixtures.*|ejemplos.*|verificacion|pruebas|_dobles)$', re.I)
SUBCADENA_PROHIBIDA = re.compile(r'fixtures|datos-reales|research', re.I)       # en rutas, como verificar_dist
NOMBRE_PROHIBIDO = re.compile(r'^(config\.json|.*\.dpapi|.*\.sqlite.*|.*\.key|.*\.jks|.*\.keystore|.*\.env|.*\.ps1|.*\.map)$', re.I)
EXCLUIDOS = ('setuptools', 'pkg_resources', '_distutils_hack', 'PyInstaller', '_pyinstaller_hooks_contrib', 'altgraph',
             'pefile', 'win32ctypes', 'packaging', 'pip')
MODULOS_DESARROLLO = ('fixtures_api', 'motor_ref', 'analitica_ref', 'ux_reglas', 'dobles')
PERFIL_PRIVADO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'research',
                                               'datos-reales', 'perfil.json'))
EXT_TEXTO = ('.js', '.mjs', '.css', '.html', '.htm', '.json', '.txt', '.svg', '.xml', '.md', '.py', '.cfg', '.ini', '.toml')
MIN_EN_BINARIO = 6


def cargar_privados(ruta: str | None) -> list[tuple[str, bytes]] | None:
    """(campo, valor en UTF-8) de la identidad real; None si el archivo no existe. Ningún valor se imprime nunca."""
    if not ruta or not os.path.isfile(ruta):
        return None
    with open(ruta, encoding='utf-8-sig') as f:
        d = json.load(f)
    d = d.get('data', d) if isinstance(d, dict) else {}
    avatar = d.get('avatar') if isinstance(d.get('avatar'), dict) else {}
    campos = {'username': d.get('username'), 'creator_user_open_id': d.get('creator_user_open_id'),
              'avatar.url': avatar.get('url')}
    return [(c, v.encode('utf-8')) for c, v in campos.items() if isinstance(v, str) and len(v) >= 3]


class Guardia:
    def __init__(self, app: str, exigir: list[str], privados: list[tuple[str, bytes]] | None = None) -> None:
        self.app = os.path.abspath(app)
        self.exigir = exigir
        self.privados = privados or []
        self.hallazgos: list[str] = []
        self.excepciones: list[str] = []      # usos de PERMITIDOS: se imprimen como AVISO (nunca pasan en silencio)
        self.revisado = {'archivos': 0, 'entradas_carchive': 0, 'modulos_pyz': 0, 'entradas_zip': 0, 'bytes': 0}
        self.modulos: set[str] = set()

    # ------------------------------------------------------------------ utilidades
    def prohibido(self, texto: str) -> None:
        if texto not in self.hallazgos:
            self.hallazgos.append(texto)

    def revisar_ruta(self, ruta: str, donde: str) -> None:
        partes = [p for p in re.split(r'[\\/]', ruta) if p]
        nombre = partes[-1] if partes else ruta
        for p in partes[:-1] + [nombre.split('.', 1)[0]]:
            if SEGMENTO_PROHIBIDO.match(p) or SUBCADENA_PROHIBIDA.search(p):
                self.prohibido(f'ruta prohibida ({p}) en {donde}: {ruta}')
                return
        if NOMBRE_PROHIBIDO.match(nombre) or (nombre.lower().endswith('.pem') and nombre.lower() != 'cacert.pem'):
            self.prohibido(f'archivo prohibido en {donde}: {ruta}')

    def revisar_modulo_nombre(self, nombre: str, donde: str) -> None:
        partes = nombre.split('.')
        if partes[0] in EXCLUIDOS:
            self.prohibido(f'módulo que debía excluirse en {donde}: {nombre}')
        for p in partes:
            if SEGMENTO_PROHIBIDO.match(p) or p in MODULOS_DESARROLLO:
                self.prohibido(f'módulo de desarrollo o de pruebas en {donde}: {nombre}')
                break

    def revisar_privados(self, datos: bytes, donde: str, es_texto: bool, utf16: bool) -> None:
        minusculas = None
        for campo, valor in self.privados:
            if not es_texto and len(valor) < MIN_EN_BINARIO:
                continue
            hallado = valor in datos or (utf16 and valor.decode('utf-8').encode('utf-16-le') in datos)
            if not hallado and es_texto:
                if minusculas is None:
                    minusculas = datos.lower()
                hallado = valor.lower() in minusculas
            if hallado:
                self.prohibido(f'dato privado de research/datos-reales (campo {campo}) en {donde}')

    def revisar_bytes(self, datos: bytes, donde: str, modulo: str | None = None, utf16: bool = False) -> None:
        self.revisado['bytes'] += len(datos)
        if self.privados:
            es_texto = modulo is not None or donde.lower().endswith(EXT_TEXTO)
            self.revisar_privados(datos, donde, es_texto, utf16)
        for m in MARCADORES:
            variantes = [m] + ([m.decode('ascii').encode('utf-16-le')] if utf16 else [])
            if any(v in datos for v in variantes):
                if modulo is not None and modulo in PERMITIDOS.get(m, ()):
                    aviso = f'«{m.decode()}» permitido solo en el módulo {modulo} (identidad de los datos sintéticos de demo, BUILD §6.3)'
                    if aviso not in self.excepciones:
                        self.excepciones.append(aviso)
                    continue
                self.prohibido(f'«{m.decode()}» aparece en {donde}')
        s = PATRON_SECRETO.search(datos)
        if s:
            self.prohibido(f'posible secreto («{s.group(1).decode()}») en {donde}')

    def revisar_zip(self, datos_o_ruta, donde: str) -> None:
        try:
            with zipfile.ZipFile(datos_o_ruta) as z:
                for info in z.infolist():
                    self.revisado['entradas_zip'] += 1
                    self.revisar_ruta(info.filename, donde)
                    if info.is_dir():
                        continue
                    nombre_mod = info.filename.rsplit('.', 1)[0].replace('/', '.') if info.filename.endswith('.pyc') else None
                    if nombre_mod:
                        if nombre_mod.endswith('.__init__'):
                            nombre_mod = nombre_mod[:-9]
                        self.modulos.add(nombre_mod)
                        self.revisar_modulo_nombre(nombre_mod, donde)
                    self.revisar_bytes(z.read(info), f'{donde} › {info.filename}', modulo=nombre_mod)
        except zipfile.BadZipFile:
            pass

    # ------------------------------------------------------------------ partes
    def revisar_carpeta(self) -> None:
        interno = os.path.join(self.app, '_internal')
        for nombre in EXCLUIDOS:
            if os.path.isdir(os.path.join(interno, nombre)):
                self.prohibido(f'el paquete trae lo que debía excluirse: _internal\\{nombre}')
        for raiz, _dirs, archivos in os.walk(self.app):
            for a in archivos:
                ruta = os.path.join(raiz, a)
                rel = os.path.relpath(ruta, self.app)
                self.revisado['archivos'] += 1
                self.revisar_ruta(rel, 'la carpeta')
                with open(ruta, 'rb') as f:
                    datos = f.read()
                self.revisar_bytes(datos, rel, utf16=True)
                if datos[:4] == b'PK\x03\x04':
                    self.revisar_zip(io.BytesIO(datos), rel)

    def revisar_exe(self) -> None:
        exe = os.path.join(self.app, 'CreatorHub.exe')
        if not os.path.isfile(exe):
            candidatos = [f for f in os.listdir(self.app) if f.lower().endswith('.exe')]
            if not candidatos:
                raise FileNotFoundError(f'No hay ningún .exe en {self.app}')
            exe = os.path.join(self.app, candidatos[0])
        from PyInstaller.archive.readers import CArchiveReader, PKG_ITEM_PYZ
        pkg = CArchiveReader(exe)
        nombre_exe = os.path.basename(exe)
        for nombre, entrada in pkg.toc.items():
            tipo = entrada[-1]
            self.revisado['entradas_carchive'] += 1
            donde = f'{nombre_exe} › {nombre}'
            self.revisar_ruta(nombre, nombre_exe)
            if tipo == PKG_ITEM_PYZ:
                self.revisar_pyz(pkg, nombre, donde)
                continue
            datos = pkg.extract(nombre)
            # 's' (script) y 'm'/'M' (módulos de arranque): código; el resto, datos o binarios
            modulo = nombre if tipo in ('s', 'm', 'M') else None
            if modulo:
                self.revisar_modulo_nombre(modulo, nombre_exe)
            self.revisar_bytes(datos, donde, modulo=modulo, utf16=modulo is None)
            if datos[:4] == b'PK\x03\x04':
                self.revisar_zip(io.BytesIO(datos), donde)

    def revisar_pyz(self, pkg, nombre: str, donde: str) -> None:
        pyz = pkg.open_embedded_archive(nombre)
        for modulo in pyz.toc:
            self.revisado['modulos_pyz'] += 1
            self.modulos.add(modulo)
            self.revisar_modulo_nombre(modulo, 'el PYZ')
            datos = pyz.extract(modulo, raw=True)      # zlib descomprimido, sin unmarshal (None: paquete PEP 420)
            if datos:
                self.revisar_bytes(datos, f'{donde} › {modulo}', modulo=modulo)

    def revisar_exigidos(self) -> None:
        for m in self.exigir:
            if m and m not in self.modulos and not any(x.startswith(m + '.') for x in self.modulos):
                self.prohibido(f'falta el módulo obligatorio «{m}» en el paquete')

    def correr(self) -> int:
        if not os.path.isdir(self.app):
            print(f'guardia_exe: no existe la carpeta {self.app}', file=sys.stderr)
            return 2
        try:
            self.revisar_carpeta()
        except OSError as e:
            print(f'guardia_exe: no se pudo leer la carpeta: {type(e).__name__}: {e}', file=sys.stderr)
            return 2
        try:
            self.revisar_exe()
        except (OSError, ValueError, RuntimeError, KeyError, ImportError) as e:
            # Lo que no se puede revisar no pasa: un .exe que no es de PyInstaller (o está dañado) es un hallazgo.
            self.prohibido(f'no se pudo revisar el CArchive/PYZ del .exe ({type(e).__name__}: {e})')
        self.revisar_exigidos()
        r = self.revisado
        resumen = (f"{r['archivos']} archivos, {r['entradas_carchive']} entradas del CArchive, {r['modulos_pyz']} módulos "
                   f"del PYZ y {r['entradas_zip']} entradas de .zip ({r['bytes'] / 1e6:.1f} MB revisados; "
                   f"{len(self.privados)} campos privados buscados)")
        for aviso in self.excepciones:
            print(f'AVISO: {aviso}')
        if self.hallazgos:
            for h in self.hallazgos:
                print(f'PROHIBIDO: {h}')
            print(f'guardia_exe: FALLA ({len(self.hallazgos)} hallazgos) · {resumen}')
            return 1
        print(f'guardia_exe: OK · {resumen}')
        return 0


def salida_como_la_consola() -> None:
    """PowerShell 5.1 decodifica la salida de un programa con la página de códigos de la consola; Python escribe en la
    del sistema (cp1252) cuando su salida va a una tubería. Se alinean para que los acentos lleguen bien."""
    try:
        import ctypes
        cp = ctypes.windll.kernel32.GetConsoleOutputCP()
        cod = 'utf-8' if cp in (0, 65001) else f'cp{cp}'
        sys.stdout.reconfigure(encoding=cod, errors='replace')
        sys.stderr.reconfigure(encoding=cod, errors='replace')
    except (AttributeError, LookupError, OSError):
        pass


def main(argv: list[str] | None = None) -> int:
    salida_como_la_consola()
    ap = argparse.ArgumentParser(description='Guardia profunda del paquete onedir de Corte')
    ap.add_argument('app', help='carpeta onedir (la que contiene CreatorHub.exe y _internal)')
    ap.add_argument('--exigir', default='', help='módulos obligatorios separados por coma (p. ej. PIL,qrcode,png)')
    ap.add_argument('--json', help='escribe aquí el informe (hallazgos y conteos)')
    ap.add_argument('--perfil-privado', default=PERFIL_PRIVADO,
                    help='perfil.json con la identidad real que no puede viajar (por omisión research/datos-reales/perfil.json)')
    a = ap.parse_args(argv)
    try:
        privados = cargar_privados(a.perfil_privado)
    except (OSError, ValueError) as e:
        print(f'guardia_exe: no se pudo leer el perfil privado: {type(e).__name__}', file=sys.stderr)
        return 2
    if privados is None:
        print('AVISO: no existe research/datos-reales/perfil.json: no se buscan datos privados en el paquete')
    elif len(privados) < 3:
        print(f'AVISO: el perfil privado solo trae {len(privados)} de 3 campos (username, creator_user_open_id, avatar.url)')
    g = Guardia(a.app, [m.strip() for m in a.exigir.split(',') if m.strip()], privados)
    codigo = g.correr()
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as f:
            json.dump({'codigo': codigo, 'hallazgos': g.hallazgos, 'excepciones': g.excepciones, 'revisado': g.revisado,
                       'campos_privados_revisados': [c for c, _ in g.privados]}, f, ensure_ascii=False, indent=1)
    return codigo


if __name__ == '__main__':
    sys.exit(main())
