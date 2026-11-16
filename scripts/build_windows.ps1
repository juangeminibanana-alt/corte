<#
  Compila Corte (CreatorHub.exe) para Windows: entorno -> interfaz (Vite) + licencias -> íconos -> PyInstaller onedir ->
  guardia -> autoprueba (2 corridas, tiempos) -> zip portátil con Instalar.ps1 (o instalador de Inno Setup con -InnoSetup).
  Base: 04 §D.2 con BUILD_SPEC C3 (Pillow entra al exe y sale de la guardia), §11.2 y las decisiones del orquestador:
    - Paso 1: NodeModulesAlDia (comun_empaquetado.ps1) adopta la marca del lock si node_modules ya coincide y si no,
      AsegurarNodeModules hace npm ci como en 04.
    - Paso 1b: scripts\generar_licencias.ps1 deja ui\dist\licencias.json (Acerca de) antes de empaquetar.
    - Paso 2: render_iconos.mjs regenera branding\ desde spec\assets y luego hace los PNG y el .ico del build.
    - Paso 5: scripts\guardia_exe.ps1 (04 §D.2 más la guardia profunda: CArchive y PYZ descomprimidos, creador_demo,
      __DOBLE_CORTE__, .map, research\, fixtures, spec\verificacion\ejemplos; exige PIL, qrcode, png, webview, creatorhub).
    - Paso 6: además de t_hub_listo_ms <= 800, la «version» del informe (si viene) debe ser la de version.json.
    - Paso 7: Inno Setup NO está autorizado: el entregable es el zip con Instalar.ps1. -InnoSetup solo si el usuario lo
      autoriza y ISCC.exe está instalado.
  Uso: powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1 [-SinUI] [-SinInstalador] [-SinPrueba] [-SinRed] [-InnoSetup]
#>
[CmdletBinding()]
param([switch]$SinUI, [switch]$SinInstalador, [switch]$SinPrueba, [switch]$SinRed, [switch]$InnoSetup, [string]$UiDist)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'comun.ps1')
. (Join-Path $PSScriptRoot 'comun_empaquetado.ps1')

# ---------------- rutas (CONTEXTO.md) ----------------
$Raiz    = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Node    = $script:NodeDir
$Npm     = Join-Path $Node 'npm.cmd'
$Py      = Join-Path $Raiz '.venv-hub\Scripts\python.exe'
$UI      = Join-Path $Raiz 'ui'
$Hub     = Join-Path $Raiz 'hub'
$Trabajo = Join-Path $Raiz 'build\windows'
$Salida  = Join-Path $Raiz 'dist'
$Iconos  = Join-Path $Trabajo 'iconos'
# Recursive build operations must remain inside this checkout.
$raizAbsoluta = [IO.Path]::GetFullPath($Raiz).TrimEnd('\') + '\'
foreach ($objetivo in @($Trabajo, $Salida, $Iconos)) {
    $absoluto = [IO.Path]::GetFullPath($objetivo)
    if (-not $absoluto.StartsWith($raizAbsoluta, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'El destino de compilación salió del repositorio.'
    }
}
$UiBundle = Join-Path $UI 'dist'
if ($UiDist) {
    if (-not $SinUI) { throw '-UiDist requiere -SinUI para usar una interfaz ya verificada.' }
    $UiBundle = (Resolve-Path -LiteralPath $UiDist).Path
    if (-not ([IO.Path]::GetFullPath($UiBundle)).StartsWith($raizAbsoluta, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'La interfaz empaquetada debe estar dentro del repositorio.'
    }
}

$version = [string](Get-Content (Join-Path $Raiz 'version.json') -Raw | ConvertFrom-Json).version
if ($version -notmatch '^\d+\.\d+\.\d+$') { throw "version.json: versión inválida '$version'" }
New-Item -ItemType Directory -Force $Trabajo, $Salida, $Iconos | Out-Null

# ---------------- 0. herramientas y entorno Python ----------------
Paso "Corte $version · herramientas y entorno"
foreach ($r in @((Join-Path $Node 'node.exe'), $Npm)) { if (-not (Test-Path $r)) { throw "No existe $r" } }
& (Join-Path $PSScriptRoot 'preparar_entorno.ps1') -SinRed:$SinRed     # crea o sincroniza .venv-hub
Ejecutar $Py @('-c', "import webview, PyInstaller, qrcode, png, PIL; import qrcode.image.pure; print('dependencias OK')")
if (-not (Test-Path (Join-Path $Hub 'creatorhub\__main__.py'))) { throw 'Falta hub\creatorhub\__main__.py (lo entrega windows-shell)' }

# ---------------- 1. interfaz ----------------
if (-not $SinUI) {
    Paso 'Interfaz: node_modules al día con el lock + vite build'
    NodeModulesAlDia $UI
    Push-Location $UI
    try { Ejecutar $Npm @('run', 'build') } finally { Pop-Location }
}
if (-not (Test-Path (Join-Path $UiBundle 'index.html'))) { throw 'Falta index.html en la interfaz para empaquetar.' }

# ---------------- 1b. licencias (Acerca de) ----------------
Paso 'Licencias: ui\dist\licencias.json (interfaz + ejecutable)'
& (Join-Path $PSScriptRoot 'generar_licencias.ps1') -Plataforma windows -Salida (Join-Path $UiBundle 'licencias.json')

# ---------------- 2. íconos ----------------
Paso 'Íconos: SVG -> PNG (resvg) -> ICO (Pillow)'
Ejecutar (Join-Path $Node 'node.exe') @((Join-Path $UI 'scripts\render_iconos.mjs'))     # branding\ desde spec\assets
Ejecutar (Join-Path $Node 'node.exe') @((Join-Path $UI 'scripts\render_iconos.mjs'), (Join-Path $Raiz 'branding\icono.svg'), $Iconos, (Join-Path $Raiz 'branding\icono_pequeno.svg'))
Ejecutar $Py @((Join-Path $Raiz 'tools\generar_ico.py'), $Iconos, (Join-Path $Iconos 'CreatorHub.ico'))

# ---------------- 3. recurso de versión del .exe ----------------
Paso 'Recurso de versión (es-MX)'
$v = $version.Split('.'); $tupla = "($($v[0]), $($v[1]), $($v[2]), 0)"
EscribirUtf8SinBom (Join-Path $Trabajo 'version_info.txt') @"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=$tupla, prodvers=$tupla, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('080a04b0', [
      StringStruct('CompanyName', 'Corte'),
      StringStruct('FileDescription', 'Corte'),
      StringStruct('FileVersion', '$version'),
      StringStruct('InternalName', 'CreatorHub'),
      StringStruct('OriginalFilename', 'CreatorHub.exe'),
      StringStruct('ProductName', 'Corte'),
      StringStruct('ProductVersion', '$version')])]),
    VarFileInfo([VarStruct('Translation', [2058, 1200])])
  ]
)
"@

# ---------------- 4. PyInstaller ----------------
Paso 'PyInstaller (onedir, sin consola, sin UPX)'
$env:CH_RAIZ = $Raiz
$env:CH_UI_DIST = $UiBundle
Ejecutar $Py @('-m', 'PyInstaller', '--noconfirm', '--clean', '--log-level', 'WARN',
    '--distpath', (Join-Path $Trabajo 'dist'), '--workpath', (Join-Path $Trabajo 'pyi'),
    (Join-Path $Hub 'CreatorHub.spec'))
$App = Join-Path $Trabajo 'dist\CreatorHub'
if (-not (Test-Path (Join-Path $App 'CreatorHub.exe'))) { throw 'PyInstaller no generó CreatorHub.exe' }

# ---------------- 5. guardia ----------------
Paso 'Guardia: sin secretos, sin datos privados ni de desarrollo y sin lo excluido'
& (Join-Path $PSScriptRoot 'guardia_exe.ps1') -App $App -Exigir @('PIL', 'qrcode', 'png', 'webview', 'creatorhub')

# ---------------- 6. autoprueba (2 corridas: la 1.ª calienta el escaneo de Defender) ----------------
if (-not $SinPrueba) {
    $informe = Join-Path $env:TEMP 'CreatorHub-autoprueba\autoprueba.json'
    foreach ($corrida in 1, 2) {
        Paso "Autoprueba del .exe ($corrida/2)"
        if (Test-Path $informe) { Remove-Item $informe -Force }
        $p = Start-Process (Join-Path $App 'CreatorHub.exe') -ArgumentList '--autoprueba' -PassThru -WindowStyle Hidden
        $null = $p.Handle                                   # sin esto, en 5.1 ExitCode puede llegar vacío
        if (-not $p.WaitForExit(60000)) { $p.Kill(); throw 'La autoprueba no terminó en 60 s' }
        if ($p.ExitCode -ne 0) { throw "La autoprueba falló (código $($p.ExitCode)). Revisa %TEMP%\CreatorHub-autoprueba\logs" }
    }
    if (-not (Test-Path $informe)) { throw "La autoprueba terminó con 0 pero no dejó $informe" }
    $t = Get-Content $informe -Raw | ConvertFrom-Json
    $campo = { param($n) if ($t.PSObject.Properties[$n]) { $t.$n } else { $null } }     # StrictMode: sin campos faltantes
    Paso ('Arranque: main {0} ms · imports {1} ms · hub listo {2} ms · CLR/edgechromium {3} ms · identidad TLS {4} ms' -f `
        (& $campo 't_main_ms'), (& $campo 't_import_ms'), (& $campo 't_hub_listo_ms'), (& $campo 't_edgechromium_ms'), (& $campo 't_identidad_tls_ms'))
    $listo = & $campo 't_hub_listo_ms'
    if ($null -eq $listo) { throw 'El informe de la autoprueba no trae t_hub_listo_ms' }
    if ([double]$listo -gt 800) { throw "El hub tardó $listo ms en estar listo (máximo 800). Revisa importaciones nuevas." }
    $vInforme = & $campo 'version'
    if ($null -eq $vInforme) { Write-Host 'Aviso: el informe de la autoprueba no trae «version» (04 §A.2 la pide)' -ForegroundColor Yellow }
    elseif ([string]$vInforme -ne $version) { throw "La autoprueba reporta la versión '$vInforme' y version.json dice '$version'" }
}

# ---------------- 7. instalador o zip ----------------
$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if ($SinInstalador) {
    $entregable = $App
} elseif ($InnoSetup) {
    if (-not $iscc) { throw 'Pediste -InnoSetup pero ISCC.exe no está instalado (requiere autorización del usuario: BUILD §12 #2)' }
    Paso 'Instalador (Inno Setup)'
    Ejecutar $iscc @('/Q', "/DVersion=$version", "/DOrigen=$App", "/DIcono=$(Join-Path $Iconos 'CreatorHub.ico')",
        "/O$Salida", (Join-Path $Raiz 'instalador\CreatorHub.iss'))
    $entregable = Join-Path $Salida "CreatorHub-Setup-$version.exe"
} else {
    Paso 'Zip portátil + Instalar.ps1'
    $tmp = Join-Path $Trabajo 'zip'
    if (-not ([IO.Path]::GetFullPath($tmp)).StartsWith($raizAbsoluta, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'El destino ZIP salió del repositorio.'
    }
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
    New-Item -ItemType Directory -Force $tmp | Out-Null
    Copy-Item $App (Join-Path $tmp 'CreatorHub') -Recurse
    Copy-Item (Join-Path $Raiz 'instalador\desinstalar.ps1') (Join-Path $tmp 'CreatorHub')     # robocopy /MIR lo conserva
    Copy-Item -Path @((Join-Path $Raiz 'instalador\Instalar.ps1'), (Join-Path $Raiz 'instalador\Instalar Corte.cmd')) -Destination $tmp
    $entregable = Join-Path $Salida "CreatorHub-$version-windows.zip"
    if (Test-Path $entregable) { Remove-Item $entregable -Force }
    Compress-Archive -Path (Join-Path $tmp '*') -DestinationPath $entregable -CompressionLevel Optimal
}

# ---------------- 8. resumen ----------------
$mb = (Get-ChildItem $App -Recurse -File | Measure-Object Length -Sum).Sum / 1MB
Paso ('Listo. Carpeta {0:N1} MB · entregable: {1}' -f $mb, $entregable)
if (Test-Path $entregable -PathType Leaf) { 'SHA-256 ' + (Get-FileHash $entregable -Algorithm SHA256).Hash }
