<#
  Guardia del paquete de Windows de Corte (04 §D.2 paso 5 con BUILD_SPEC C3 y §11.6). La corre build_windows.ps1 en el
  paso 5; también se puede correr sola sobre cualquier carpeta onedir.
  Falla (código 1) si el paquete contiene:
    - archivos prohibidos: config.json, *.dpapi, *.sqlite*, *.key, *.jks, *.keystore, *.env, *.ps1, *.map, *.pem (salvo cacert.pem);
    - rutas con research, datos-reales o fixtures, o carpetas spec/verificacion/ejemplos, pruebas o _dobles;
    - lo que debía excluirse: setuptools, pkg_resources, _distutils_hack y las dependencias de compilación (C3: Pillow SÍ va);
    - un patrón de secreto, o las cadenas creador_demo o __DOBLE_CORTE__: en los archivos de la carpeta y, descomprimidos,
      en el CArchive del .exe, en cada módulo del PYZ y en base_library.zip (tools\guardia_exe.py). Única excepción:
      creador_demo dentro del módulo creatorhub.demo.transporte (identidad de los datos sintéticos de demo, BUILD §6.3),
      que se informa con una línea «AVISO:»; en cualquier otro módulo, archivo, .zip o en la interfaz es una falla.
    - -Exigir: módulos que deben estar (build_windows.ps1 exige PIL, qrcode, png, webview y creatorhub).
  Uso: powershell -NoProfile -ExecutionPolicy Bypass -File scripts\guardia_exe.ps1 -App <carpeta onedir> [-Exigir PIL,qrcode]
#>
[CmdletBinding()]
param([Parameter(Mandatory = $true)][string]$App, [string[]]$Exigir = @())
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'comun.ps1')
. (Join-Path $PSScriptRoot 'comun_empaquetado.ps1')
$Raiz = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Py = Join-Path $Raiz '.venv-hub\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $App -PathType Container)) { throw "No existe la carpeta $App" }
$App = (Resolve-Path -LiteralPath $App).Path

# 1) nombres y rutas (04 §D.2 paso 5, más .map y las rutas de desarrollo)
$prohibidos = @(Get-ChildItem -LiteralPath $App -Recurse -File | Where-Object {
    $rel = $_.FullName.Substring($App.Length)                 # solo lo que hay DENTRO del paquete
    ($_.Name -match '^(config\.json|.*\.dpapi|.*\.sqlite.*|.*\.key|.*\.jks|.*\.keystore|.*\.env|.*\.ps1|.*\.map)$') -or
    ($_.Name -like '*.pem' -and $_.Name -ne 'cacert.pem') -or
    ($rel -match '\\(research|datos-reales|fixtures[^\\]*|pruebas|_dobles)\\') -or
    ($rel -match '\\verificacion\\ejemplos') })
$prohibidos | ForEach-Object { Write-Host "PROHIBIDO: $($_.FullName)" -ForegroundColor Red }

# 2) lo que debía excluirse (C3: PIL ya no está en esta lista: Pillow entra al exe)
$sobran = @(@('setuptools', 'pkg_resources', '_distutils_hack', 'PyInstaller', 'altgraph', 'pefile', 'win32ctypes', 'packaging') |
    Where-Object { Test-Path -LiteralPath (Join-Path $App "_internal\$_") })
$sobran | ForEach-Object { Write-Host "PROHIBIDO: el paquete trae _internal\$_ (debía excluirse)" -ForegroundColor Red }

# 3) secretos en texto plano (04 §D.2 paso 5)
$patron = '"(app_secret|access_token|refresh_token)"\s*:\s*"[^"]{8,}"'
$hallazgos = @(Get-ChildItem -LiteralPath $App -Recurse -File -Include *.js, *.json, *.html, *.txt, *.py, *.cfg |
    Select-String -Pattern $patron -List)
$hallazgos | ForEach-Object { Write-Host "POSIBLE SECRETO en $($_.Path)" -ForegroundColor Red }

# 4) guardia profunda: CArchive, PYZ y .zip descomprimidos, marcadores, módulos excluidos y exigidos
$argumentos = @('-I', (Join-Path $Raiz 'tools\guardia_exe.py'), $App)
$exigidos = @($Exigir | ForEach-Object { $_ -split ',' } | Where-Object { $_ })
if ($exigidos.Count -gt 0) { $argumentos += @('--exigir', ($exigidos -join ',')) }
$previo = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
try {
    & $Py @argumentos 2>&1 | ForEach-Object { TextoDeSalida $_ } | ForEach-Object {
        if ($_ -like 'PROHIBIDO:*') { Write-Host $_ -ForegroundColor Red }
        elseif ($_ -like 'AVISO:*') { Write-Host $_ -ForegroundColor Yellow }
        else { Write-Host $_ } }
}
finally { $ErrorActionPreference = $previo }
$profunda = $LASTEXITCODE

if ($profunda -eq 2) { throw 'La guardia no pudo leer el paquete (tools\guardia_exe.py salió con 2)' }
if ($prohibidos.Count -gt 0 -or $sobran.Count -gt 0) { throw 'El paquete contiene archivos prohibidos o lo que debía excluirse' }
if ($hallazgos.Count -gt 0) { throw 'Posible secreto empaquetado' }
if ($profunda -ne 0) { throw 'La guardia profunda encontró contenido prohibido (ver las líneas PROHIBIDO)' }
Write-Host 'Guardia: OK' -ForegroundColor Green
