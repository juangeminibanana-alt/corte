<#
  Genera ui\dist\licencias.json (Ajustes > Acerca de > Licencias; lo sirven los estáticos del hub y ServidorAssets).
  Fuentes: ui\package-lock.json (dependencias de ejecución, con el texto de licencia de ui\node_modules) y, para Windows,
  la sección «entran en CreatorHub.exe» de hub\requirements.txt (texto de licencia del .dist-info en .venv-hub), Python,
  el cargador de WebView2 y el cargador de PyInstaller. El trabajo lo hace tools\generar_licencias.py; si falta un texto,
  una versión no coincide o el JSON traería algo que verificar_dist o la guardia rechazan, falla y no escribe nada.
  build_windows.ps1 y build_android.ps1 lo corren después de `npm run build` (vite vacía ui\dist en cada build).
  Uso: powershell -NoProfile -ExecutionPolicy Bypass -File scripts\generar_licencias.ps1 [-Plataforma windows|android] [-Salida <ruta>]
#>
[CmdletBinding()]
param([ValidateSet('windows', 'android')][string]$Plataforma = 'windows', [string]$Salida)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'comun.ps1')
$Raiz = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Py = Join-Path $Raiz '.venv-hub\Scripts\python.exe'
if (-not $Salida) { $Salida = Join-Path $Raiz 'ui\dist\licencias.json' }
if (-not (Test-Path -LiteralPath $Py)) { throw "Falta $Py (corre scripts\preparar_entorno.ps1)" }
if (-not (Test-Path -LiteralPath (Join-Path $Raiz 'ui\node_modules'))) { throw 'Falta ui\node_modules (corre npm ci en ui\)' }
$carpeta = Split-Path -Parent $Salida
if (-not (Test-Path -LiteralPath $carpeta)) {
    Write-Host "Aviso: $carpeta no existía (normalmente la crea npm run build); se crea solo para licencias.json." -ForegroundColor Yellow
}
Ejecutar $Py @('-I', (Join-Path $Raiz 'tools\generar_licencias.py'), '--raiz', $Raiz, '--salida', $Salida, '--plataforma', $Plataforma)
