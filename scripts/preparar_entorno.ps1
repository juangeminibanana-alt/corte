<#
  Crea o sincroniza el entorno Python del hub (.venv-hub) con hub\requirements.txt y lo comprueba (pip check +
  importaciones). Idempotente: si ya está al día, pip no descarga nada. build_windows.ps1 lo corre en el paso 0.
  Sin internet: -SinRed instala desde vendor\wheels (se llena una vez, con red, con -DescargarRuedas).
  Uso: powershell -ExecutionPolicy Bypass -File scripts\preparar_entorno.ps1 [-Venv <ruta>] [-SinRed] [-DescargarRuedas]
#>
[CmdletBinding()]
param([string]$Venv, [string]$Requisitos, [switch]$SinRed, [switch]$DescargarRuedas)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'comun.ps1')
$Raiz = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $Venv) { $Venv = Join-Path $Raiz '.venv-hub' }
if (-not $Requisitos) { $Requisitos = Join-Path $Raiz 'hub\requirements.txt' }
$Ruedas = Join-Path $Raiz 'vendor\wheels'
$Py = Join-Path $Venv 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Requisitos)) { throw "Falta $Requisitos" }

if (-not (Test-Path -LiteralPath $Py)) {
    Paso "Creando $Venv con Python 3.12"
    $lanzador = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($lanzador) { Ejecutar $lanzador.Source @('-3.12', '-m', 'venv', $Venv) } else { Ejecutar 'python.exe' @('-m', 'venv', $Venv) }
}
if ("$(Capturar $Py @('-c', 'import sys; print(sys.version_info[:2] == (3, 12))'))".Trim() -ne 'True') { throw "$Py no es Python 3.12" }

$pip = @('-m', 'pip', '--disable-pip-version-check', '--no-input')
if ($DescargarRuedas) {
    Paso "Ruedas para compilar sin internet -> $Ruedas"
    Ejecutar $Py ($pip + @('wheel', '-r', $Requisitos, '-w', $Ruedas))
}
Paso "Instalando $(Split-Path $Requisitos -Leaf) en $Venv"
if ($SinRed) { Ejecutar $Py ($pip + @('install', '--no-index', '--find-links', $Ruedas, '-r', $Requisitos)) }
else { Ejecutar $Py ($pip + @('install', '-r', $Requisitos)) }
Ejecutar $Py ($pip + @('check'))
Ejecutar $Py @('-c', "import webview, PyInstaller, qrcode, png, PIL; import qrcode.image.pure; print('entorno OK')")
