<#
  Compila Corte para Android SIN internet (caché de Gradle) y verifica el APK.
  Base: 04 §D.3 (contenido exacto) con BUILD_SPEC §7.1 y §11.3; agregados de build-empaquetado:
    - Paso 1: NodeModulesAlDia (comun_empaquetado.ps1) adopta la marca del lock si node_modules ya coincide y si no,
      AsegurarNodeModules hace npm ci como en 04.
    - Paso 1b: scripts\generar_licencias.ps1 -Plataforma android deja ui\dist\licencias.json (solo la interfaz: el APK
      no lleva otras dependencias) antes de que Gradle copie ui\dist a assets\web.
    - -UiDist <carpeta>: otra interfaz ya compilada (p. ej. android\ui_prueba de android-shell) vía -PchUiDist
      (BUILD §7.1). Implica -SinUI y no escribe licencias.json en esa carpeta (no es de este script).
    - Paso 4: además de 04 §D.3, deben estar LOS 5 permisos (ni uno de más ni uno de menos) y el contenido de
      assets\web no puede traer creador_demo, __DOBLE_CORTE__ ni la identidad real de research\datos-reales\perfil.json
      (username, open_id, URL del avatar; BUILD §11.6: se nombra el campo, nunca el valor).
  Uso: powershell -ExecutionPolicy Bypass -File scripts\build_android.ps1 [-Tipo release|debug] [-SinUI] [-UiDist <carpeta>] [-Online] [-Instalar] [-SinDaemon]
#>
[CmdletBinding()]
param(
    [ValidateSet('release', 'debug')][string]$Tipo = 'release',
    [switch]$SinUI, [string]$UiDist, [switch]$Online, [switch]$Instalar, [switch]$SinDaemon
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'comun.ps1')
. (Join-Path $PSScriptRoot 'comun_empaquetado.ps1')

$Raiz    = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Npm     = Join-Path $script:NodeDir 'npm.cmd'
$UI      = Join-Path $Raiz 'ui'
$Android = Join-Path $Raiz 'android'
$Salida  = Join-Path $Raiz 'dist'
$Gradle  = 'D:\android-toolchain\gradle-8.11.1\bin\gradle.bat'
$BT      = 'D:\Android\Sdk\build-tools\35.0.0'
$Adb     = 'D:\Android\Sdk\platform-tools\adb.exe'
$env:JAVA_HOME        = 'D:\android-toolchain\jdk-17.0.19+10'
$env:ANDROID_HOME     = 'D:\Android\Sdk'
$env:ANDROID_SDK_ROOT = 'D:\Android\Sdk'
$env:GRADLE_USER_HOME = 'D:\android-toolchain\gradle-home'
$env:PATH = "$env:JAVA_HOME\bin;$env:PATH"

$cfg = Get-Content (Join-Path $Raiz 'version.json') -Raw | ConvertFrom-Json
$version = [string]$cfg.version
$codigo  = [int]$cfg.android_version_code
if ($version -notmatch '^\d+\.\d+\.\d+$' -or $codigo -lt 1) { throw 'version.json inválido' }

# ---------------- 0. firma estable ----------------
$ks = Join-Path $env:USERPROFILE '.android\debug.keystore'
if (-not (Test-Path $ks)) {
    throw "Falta $ks. Restaura tu respaldo: con otra llave el teléfono no acepta la actualización (habría que desinstalar y perder la copia sin conexión)."
}

# ---------------- 1. interfaz ----------------
if ($UiDist) {
    if (-not (Test-Path -LiteralPath (Join-Path $UiDist 'index.html'))) { throw "Falta $UiDist\index.html (-UiDist)" }
    $UiDist = (Resolve-Path -LiteralPath $UiDist).Path
    Paso "Interfaz ya compilada: $UiDist (-PchUiDist; sin vite build ni licencias.json)"
} else {
    if (-not $SinUI) {
        Paso 'Interfaz: node_modules al día con el lock + vite build'
        NodeModulesAlDia $UI
        Push-Location $UI
        try { Ejecutar $Npm @('run', 'build') } finally { Pop-Location }
    }
    if (-not (Test-Path (Join-Path $UI 'dist\index.html'))) { throw 'Falta ui\dist\index.html' }

    # ---------------- 1b. licencias (Acerca de) ----------------
    Paso 'Licencias: ui\dist\licencias.json (interfaz)'
    & (Join-Path $PSScriptRoot 'generar_licencias.ps1') -Plataforma android -Salida (Join-Path $UI 'dist\licencias.json')
}

# ---------------- 2. local.properties ----------------
[IO.File]::WriteAllText((Join-Path $Android 'local.properties'), "sdk.dir=D\:\\Android\\Sdk`r`n")

# ---------------- 3. Gradle (syncWebAssets copia ui\dist -> app\src\main\assets\web) ----------------
$tarea = if ($Tipo -eq 'release') { ':app:assembleRelease' } else { ':app:assembleDebug' }
$argumentos = @('-p', $Android, '--console=plain', "-PchVersionName=$version", "-PchVersionCode=$codigo", $tarea)
$argumentos += '-PchCloud=true'
if ($UiDist)      { $argumentos = @("-PchUiDist=$($UiDist -replace '\\', '/')") + $argumentos }
if (-not $Online) { $argumentos = @('--offline') + $argumentos }
if ($SinDaemon)   { $argumentos = @('--no-daemon') + $argumentos }
Paso "Gradle $tarea $(if ($Online) { '(en línea)' } else { '(--offline)' })"
Ejecutar $Gradle $argumentos
$apk = Join-Path $Android "app\build\outputs\apk\$Tipo\app-$Tipo.apk"
if (-not (Test-Path $apk)) { throw "No se generó $apk" }

# ---------------- 4. verificación ----------------
Paso 'Verificando versión, SDK, permisos y firma'
$badging = Capturar (Join-Path $BT 'aapt2.exe') @('dump', 'badging', $apk)
foreach ($e in @("versionCode='$codigo'", "versionName='$version", "minSdkVersion:'26'", "targetSdkVersion:'35'")) {
    if (-not ($badging -match [regex]::Escape($e))) { throw "El APK no cumple: $e" }
}
if ($Tipo -eq 'release') {
    if ($badging -match 'application-debuggable') { throw 'El APK release no debe permitir depuración.' }
    if (-not ($badging -match "package: name='app.creatorhub'")) { throw 'Cambió el identificador de la app: no sería una actualización compatible.' }
    Paso 'Release optimizado con certificado histórico compatible (Android Debug heredado; no listo para Google Play)'
}
$permitidos = @('android.permission.INTERNET', 'android.permission.ACCESS_NETWORK_STATE', 'android.permission.CAMERA',
                'android.permission.POST_NOTIFICATIONS', 'android.permission.RECEIVE_BOOT_COMPLETED')
$permisos = $badging | Select-String "uses-permission: name='([^']+)'" | ForEach-Object { $_.Matches[0].Groups[1].Value }
$extra = @($permisos | Where-Object { $permitidos -notcontains $_ })
if ($extra.Count -gt 0) { throw "Permisos no previstos: $($extra -join ', ')" }
$faltan = @($permitidos | Where-Object { @($permisos) -notcontains $_ })
if ($faltan.Count -gt 0) { throw "Faltan permisos de BUILD §7.1: $($faltan -join ', ')" }

$firma = Capturar (Join-Path $BT 'apksigner.bat') @('verify', '--print-certs', $apk)
$m = [regex]::Match(($firma -join "`n"), 'Signer #1 certificate SHA-256 digest: ([0-9a-f]{64})')
if (-not $m.Success) { throw 'apksigner no reportó la huella del certificado' }
$huella = $m.Groups[1].Value
$archivoHuella = Join-Path $Android 'firma_esperada.txt'
if (Test-Path $archivoHuella) {
    if ((Get-Content $archivoHuella -Raw).Trim() -ne $huella) { throw 'La firma cambió: el teléfono rechazaría la actualización.' }
} else { [IO.File]::WriteAllText($archivoHuella, $huella) }

# Identidad real (BUILD §11.6): username, open_id y URL del avatar de research\datos-reales\perfil.json, si existe.
# Solo se nombra el campo, nunca el valor.
$privados = @()
$perfil = Join-Path $Raiz 'research\datos-reales\perfil.json'
function ValorDe($objeto, [string]$nombre) {
    if ($null -ne $objeto -and $objeto.PSObject.Properties[$nombre]) { return $objeto.$nombre }
    return $null
}
if (Test-Path -LiteralPath $perfil) {
    $json = Get-Content -LiteralPath $perfil -Raw -Encoding UTF8 | ConvertFrom-Json
    $d = ValorDe $json 'data'
    if ($null -eq $d) { $d = $json }
    $campos = @(@('username', (ValorDe $d 'username')), @('creator_user_open_id', (ValorDe $d 'creator_user_open_id')),
                @('avatar.url', (ValorDe (ValorDe $d 'avatar') 'url')))
    foreach ($par in $campos) { if ($par[1] -is [string] -and $par[1].Length -ge 3) { $privados += , $par } }
}
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [IO.Compression.ZipFile]::OpenRead($apk)
try {
    $malos = @($zip.Entries | Where-Object { $_.FullName -match '(config\.json|\.dpapi|\.sqlite|\.pem|\.jks|\.keystore|\.map)$' -or $_.FullName -match 'datos-reales|fixtures|research' })
    if ($malos.Count -gt 0) { throw "Archivos prohibidos en el APK: $(($malos | ForEach-Object FullName) -join ', ')" }
    $patron = [regex]'"(app_secret|access_token|refresh_token)"\s*:\s*"[^"]{8,}"'
    $marcadores = @('creador_demo', '__DOBLE_CORTE__')
    foreach ($e in @($zip.Entries | Where-Object { $_.FullName -like 'assets/web/*' -and $_.FullName -match '\.(js|json|html|css|txt)$' })) {
        $lector = New-Object IO.StreamReader($e.Open())
        try {
            $texto = $lector.ReadToEnd()
            if ($patron.IsMatch($texto)) { throw "Posible secreto en $($e.FullName)" }
            foreach ($mk in $marcadores) { if ($texto.Contains($mk)) { throw "«$mk» aparece en $($e.FullName) (datos o dobles de desarrollo)" } }
            foreach ($par in $privados) {
                if ($texto.IndexOf([string]$par[1], [StringComparison]::OrdinalIgnoreCase) -ge 0) { throw "Dato privado de research\datos-reales (campo $($par[0])) en $($e.FullName)" }
            }
        } finally { $lector.Dispose() }
    }
} finally { $zip.Dispose() }
if ($privados.Count -gt 0) { Write-Host "Sin datos privados en assets\web ($($privados.Count) campos de research\datos-reales\perfil.json revisados)" }

# ---------------- 5. entregable ----------------
New-Item -ItemType Directory -Force $Salida | Out-Null
$sufijo = if ($Tipo -eq 'debug') { '-debug' } else { '' }
$destino = Join-Path $Salida "CreatorHub-$version$sufijo.apk"
Copy-Item $apk $destino -Force
Paso ('APK listo: {0} ({1:N0} KB) · SHA-256 {2}' -f $destino, ((Get-Item $destino).Length / 1KB), (Get-FileHash $destino -Algorithm SHA256).Hash)

# ---------------- 6. instalar (opcional) ----------------
if ($Instalar) {
    $conectados = @(Capturar $Adb @('devices') | Select-String "`tdevice$")
    if ($conectados.Count -eq 0) { throw 'No hay teléfono conectado por USB con depuración activada (adb devices).' }
    Ejecutar $Adb @('install', '-r', $destino)
}
