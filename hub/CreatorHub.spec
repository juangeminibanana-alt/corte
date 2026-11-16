# -*- mode: python ; coding: utf-8 -*-
# Receta de PyInstaller de Corte (CreatorHub.exe): 04 §A.12 y §D.4 con BUILD_SPEC C3 y §6.1 (build-empaquetado).
# La corre scripts\build_windows.ps1 (paso 4) con CH_RAIZ = raíz del proyecto, después de dejar ui\dist (paso 1, con
# licencias.json), build\windows\iconos\CreatorHub.ico (paso 2) y build\windows\version_info.txt (paso 3, «Corte»).
#   - onedir, sin consola, sin UPX.
#   - Datos: ui\dist -> _internal\ui · CreatorHub.ico -> _internal\recursos · version.json (raíz) -> _internal\creatorhub
#     (config.VERSION lo lee con importlib.resources) · collect_data_files('creatorhub', excludes=['**/pruebas/**'])
#     (almacen\schema.sql, almacen\migraciones\*.sql, local\plantillas.json, …).
#   - C3: Pillow ENTRA al exe (imagenes/ y demo/ lo importan de forma perezosa): ya no está en excludes ni en la guardia.
#   - Fuera del exe: las dependencias de compilación (PyInstaller y su cadena, setuptools & cía., pip) y tkinter,
#     unittest, pydoc, test. NO agregar "distutils": el hook de PyInstaller lo redirige a setuptools._distutils y falla
#     ("already imported as ExcludedModule"); con setuptools excluido, distutils queda fuera solo (probado en 04 §D.6).
#   - Nunca research/, datos-reales/, fixtures, spec/, pruebas ni config.json: la guardia del paso 5 lo comprueba.
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

RAIZ = os.environ["CH_RAIZ"]
HUB = os.path.join(RAIZ, "hub")
TRABAJO = os.path.join(RAIZ, "build", "windows")
ICO = os.path.join(TRABAJO, "iconos", "CreatorHub.ico")
VERSION_INFO = os.path.join(TRABAJO, "version_info.txt")
UI_DIST = os.environ.get("CH_UI_DIST", os.path.join(RAIZ, "ui", "dist"))
VERSION_JSON = os.path.join(RAIZ, "version.json")

for _requisito in (os.path.join(HUB, "creatorhub", "__main__.py"), os.path.join(UI_DIST, "index.html"),
                   VERSION_JSON, ICO, VERSION_INFO):
    if not os.path.isfile(_requisito):
        raise SystemExit(f"CreatorHub.spec: falta {_requisito} (compila con scripts\\build_windows.ps1)")

# collect_data_files y collect_submodules buscan el paquete creatorhub en sys.path (pathex solo vale para Analysis).
if HUB not in sys.path:
    sys.path.insert(0, HUB)


def _fuera_de_pruebas(nombre: str) -> bool:
    return "pruebas" not in nombre.split(".")


DATOS = [(UI_DIST, "ui"),
         (ICO, "recursos"),
         (VERSION_JSON, "creatorhub")]
DATOS += collect_data_files("creatorhub", excludes=["**/pruebas/**"])

# Todos los módulos del hub, aunque alguno se importe por nombre (fábricas de interfaces.py): sin pruebas.
OCULTOS = collect_submodules("creatorhub", filter=_fuera_de_pruebas)

EXCLUIDOS = ["tkinter", "unittest", "pydoc", "test",
             # cffi._shimmed_dist_utils arrastra setuptools & cía. (solo sirve para compilar extensiones)
             "setuptools", "pkg_resources", "_distutils_hack",
             # dependencias de compilación de hub\requirements.txt: nunca en tiempo de ejecución
             "PyInstaller", "_pyinstaller_hooks_contrib", "altgraph", "pefile", "peutils", "ordlookup",
             "win32ctypes", "packaging", "pip"]

a = Analysis(
    [os.path.join(HUB, "creatorhub", "__main__.py")],
    pathex=[HUB],
    datas=DATOS,
    hiddenimports=OCULTOS,
    excludes=EXCLUIDOS,
    optimize=1,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="CreatorHub", console=False,
          icon=ICO, version=VERSION_INFO, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="CreatorHub", upx=False)
